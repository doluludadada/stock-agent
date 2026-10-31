import asyncio
import time
from collections.abc import Collection
from datetime import date, datetime, timedelta

import httpx
from bs4 import BeautifulSoup

from a_domain.model.fundamentals.fiscal_quarter import FiscalQuarter
from a_domain.model.fundamentals.quarter_eps import EpsFilings, QuarterEps
from a_domain.ports.market.fundamentals_provider import IFundamentalsProvider
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.system.market_clock import IMarketClock
from a_domain.types.enums import MarketType
from b_application.config.sources_config import MopsSources
from c_infrastructure.database.db_connector import DatabaseConnector
from c_infrastructure.database.models.quarter_eps_dto import QuarterEpsDTO
from c_infrastructure.market.twse_provider import ROC_YEAR_OFFSET


def parse_cumulative_eps(html: str, mops: MopsSources) -> dict[str, float] | None:
    """
    Cumulative basic EPS per company from one ajax_t163sb04 page.

    {} when the season has no filings yet. None for a page that is neither (an error or throttle page), or a table
    missing the company-id or EPS header, so a format change fails the quarter instead of returning partial data.
    """
    tables = BeautifulSoup(html, "lxml").find_all("table", class_="hasBorder")

    if not tables:
        return {} if mops.no_data_marker in html else None

    result: dict[str, float] = {}

    for table in tables:
        rows = table.find_all("tr")
        header = [_cell_text(cell) for cell in rows[0].find_all("th")] if rows else []
        eps_index = next((index for index, name in enumerate(header) if name.startswith(mops.eps_header_prefix)), None)

        if mops.company_id_header not in header or eps_index is None:
            return None

        id_index = header.index(mops.company_id_header)

        for row in rows[1:]:
            cells = [_cell_text(cell) for cell in row.find_all("td")]

            if len(cells) != len(header):
                continue

            try:
                result[cells[id_index]] = float(cells[eps_index].replace(",", ""))
            except ValueError:
                continue

    return result


def _cell_text(cell) -> str:
    # Headers wrap with <br> inside the column name, so all whitespace goes.
    return "".join(cell.get_text().split())


class MopsFundamentalsProvider(IFundamentalsProvider):
    """
    Cumulative EPS from the MOPS bulk income statements (one page per market and quarter), cached in SQLite.
    Industry from the MOPS income-statement summaries on the TWSE and TPEX OpenAPI, cached in memory.

    A quarter's cached page is final, and never fetched again, once it was fetched after the quarter's last filing
    deadline plus grace and is not empty. Any other page is reused for PROVISIONAL_MAX_AGE.
    """

    TYPEK = {MarketType.TWSE: "sii", MarketType.TPEX: "otc"}
    PROVISIONAL_MAX_AGE = timedelta(hours=6)
    INDUSTRY_MAX_AGE = timedelta(hours=24)
    REQUEST_INTERVAL_SECONDS = 2.0
    TIMEOUT_SECONDS = 60.0

    def __init__(self, db: DatabaseConnector, market_clock: IMarketClock, mops: MopsSources, logger: ILoggingProvider) -> None:
        self._db = db
        self._mops = mops
        self._industry_sources = {
            MarketType.TWSE: (mops.twse_industries_url, mops.twse_industry_company_field),
            MarketType.TPEX: (mops.tpex_industries_url, mops.tpex_industry_company_field),
        }
        self._clock = market_clock
        self._logger = logger
        self._last_request_at: float | None = None
        self._industries: dict[MarketType, dict[str, str]] = {}
        self._industries_fetched_at: dict[MarketType, datetime] = {}

    async def fetch_cumulative_eps(self, quarters: Collection[FiscalQuarter]) -> EpsFilings:
        today = self._clock.today()
        filings: dict[FiscalQuarter, QuarterEps | None] = {}

        for quarter in sorted(quarters, reverse=True):
            pages = [await self._page(market, quarter, today) for market in self.TYPEK]
            present = [page for page, _ in pages if page is not None]

            if len(present) < len(pages):
                filings[quarter] = None
                continue

            cumulative_eps = {company: eps for page in present for company, eps in page.cumulative_eps.items()}
            # Eps shows when its filings were fetched as Taiwan wall-clock time.
            fetched_at = self._clock.to_market_datetime(min(page.fetched_at for page in present))
            refresh_failed = any(failed for _, failed in pages)
            filings[quarter] = QuarterEps(
                quarter=quarter, cumulative_eps=cumulative_eps, fetched_at=fetched_at, refresh_failed=refresh_failed
            )

        return filings

    async def fetch_industries(self) -> dict[str, str]:
        now = self._clock.now()
        stale = [
            market
            for market in self._industry_sources
            if market not in self._industries_fetched_at or now - self._industries_fetched_at[market] >= self.INDUSTRY_MAX_AGE
        ]

        if stale:
            async with httpx.AsyncClient(timeout=self.TIMEOUT_SECONDS) as client:
                for market in stale:
                    url, id_field = self._industry_sources[market]

                    try:
                        response = await client.get(url)
                        response.raise_for_status()
                        self._industries[market] = {
                            str(row[id_field]).strip(): str(row[self._mops.industry_field]).strip()
                            for row in response.json()
                            if row.get(id_field) and row.get(self._mops.industry_field)
                        }
                        self._industries_fetched_at[market] = now
                    except Exception as error:
                        self._logger.warning(f"MOPS industries for {market.value} unavailable: {error}")

        industries: dict[str, str] = {}

        for market_industries in self._industries.values():
            industries.update(market_industries)

        return industries

    async def _page(self, market: MarketType, quarter: FiscalQuarter, today: date) -> tuple[QuarterEpsDTO | None, bool]:
        """The market's page for the quarter, if any, and whether it is an old page served because its refresh failed."""
        label = f"MOPS {quarter} {self.TYPEK[market]}"
        cached = await self._load(market, quarter)
        now = self._clock.now()

        if cached is not None and self._is_reusable(cached, quarter, now):
            self._logger.debug(f"{label}: cached page, {len(cached.cumulative_eps)} companies")
            return cached, False

        cumulative_eps = await self._download(market, quarter)

        if cumulative_eps == {} and quarter.is_final_on(today):
            self._logger.warning(f"{label}: empty page for a quarter whose filing deadline has passed; not cached")
            cumulative_eps = None

        if cumulative_eps is None:
            if cached is not None:
                fetched_at = self._clock.to_market_datetime(cached.fetched_at)
                self._logger.warning(f"{label}: refresh failed, using the page fetched at {fetched_at:%Y-%m-%d %H:%M}")

            return cached, cached is not None

        page = QuarterEpsDTO(
            market=market.value, year=quarter.year, quarter=quarter.quarter, fetched_at=now, cumulative_eps=cumulative_eps
        )
        await self._save(page)
        self._logger.info(f"{label}: fetched {len(cumulative_eps)} companies")

        return page, False

    def _is_reusable(self, page: QuarterEpsDTO, quarter: FiscalQuarter, now: datetime) -> bool:
        if page.cumulative_eps and quarter.is_final_on(self._clock.to_trading_date(page.fetched_at)):
            return True

        return now - page.fetched_at < self.PROVISIONAL_MAX_AGE

    async def _download(self, market: MarketType, quarter: FiscalQuarter) -> dict[str, float] | None:
        form = {
            "encodeURIComponent": "1",
            "step": "1",
            "firstin": "1",
            "off": "1",
            "isQuery": "Y",
            "TYPEK": self.TYPEK[market],
            "year": str(quarter.year - ROC_YEAR_OFFSET),
            "season": f"{quarter.quarter:02d}",
        }

        await self._wait_for_request_slot()

        try:
            async with httpx.AsyncClient(timeout=self.TIMEOUT_SECONDS) as client:
                response = await client.post(self._mops.eps_url, data=form)
                response.raise_for_status()
        except Exception as error:
            self._logger.warning(f"MOPS {quarter} {self.TYPEK[market]}: request failed: {error}")
            return None

        cumulative_eps = parse_cumulative_eps(response.text, self._mops)

        if cumulative_eps is None:
            self._logger.warning(f"MOPS {quarter} {self.TYPEK[market]}: unrecognised page ({len(response.text)} bytes)")

        return cumulative_eps

    async def _wait_for_request_slot(self) -> None:
        # A cold load sends ten requests to a shared public service, so they go one at a time, spaced apart.
        if self._last_request_at is not None:
            await asyncio.sleep(max(0.0, self.REQUEST_INTERVAL_SECONDS - (time.monotonic() - self._last_request_at)))

        self._last_request_at = time.monotonic()

    async def _load(self, market: MarketType, quarter: FiscalQuarter) -> QuarterEpsDTO | None:
        async with self._db.get_session() as session:
            return await session.get(QuarterEpsDTO, (market.value, quarter.year, quarter.quarter))

    async def _save(self, page: QuarterEpsDTO) -> None:
        async with self._db.get_session() as session:
            await session.merge(page)
            await session.commit()
