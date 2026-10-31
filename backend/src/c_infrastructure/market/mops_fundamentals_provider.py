import asyncio
import time
from collections.abc import Collection
from dataclasses import replace
from datetime import date, datetime, timedelta
from typing import override

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


class MopsFundamentalsProvider(IFundamentalsProvider):
    """
    Cumulative EPS from the MOPS bulk income statements (one page per market and quarter), cached in SQLite.
    Industry from the MOPS income-statement summaries on the TWSE and TPEX OpenAPI, cached in memory.

    A quarter's cached page is final, and never fetched again, once it was fetched after the quarter's last filing
    deadline plus grace and is not empty. Any other page is reused for `provisional_page_max_age_hours`.
    """

    def __init__(self, db: DatabaseConnector, market_clock: IMarketClock, mops: MopsSources, logger: ILoggingProvider) -> None:
        self._db = db
        self._mops = mops
        self._market_codes = {MarketType.TWSE: mops.twse_market_code, MarketType.TPEX: mops.tpex_market_code}
        self._industry_sources = {
            MarketType.TWSE: (mops.twse_industries_url, mops.twse_industry_company_field),
            MarketType.TPEX: (mops.tpex_industries_url, mops.tpex_industry_company_field),
        }
        self._provisional_page_max_age = timedelta(hours=mops.provisional_page_max_age_hours)
        self._industry_max_age = timedelta(hours=mops.industry_max_age_hours)
        self._clock = market_clock
        self._logger = logger
        self._last_request_at: float | None = None
        self._industries: dict[MarketType, dict[str, str]] = {}
        self._industries_fetched_at: dict[MarketType, datetime] = {}

    @override
    async def fetch_cumulative_eps(self, quarters: Collection[FiscalQuarter]) -> EpsFilings:
        today = self._clock.today()
        filings: dict[FiscalQuarter, QuarterEps | None] = {}

        for quarter in sorted(quarters, reverse=True):
            pages = [await self.fetch_page(market, quarter, today) for market in self._market_codes]
            present = [page for page in pages if page is not None]

            if len(present) < len(pages):
                filings[quarter] = None
                continue

            filings[quarter] = QuarterEps(
                quarter=quarter,
                cumulative_eps={company: eps for page in present for company, eps in page.cumulative_eps.items()},
                # Eps shows when its filings were fetched as Taiwan wall-clock time.
                fetched_at=self._clock.to_market_datetime(min(page.fetched_at for page in present)),
                refresh_failed=any(page.refresh_failed for page in present),
            )

        return filings

    @override
    async def fetch_page(self, market: MarketType, quarter: FiscalQuarter, today: date) -> QuarterEps | None:
        label = f"MOPS {quarter} {self._market_codes[market]}"
        cached = await self.load_page(market, quarter)
        now = self._clock.now()

        if cached is not None and self.is_reusable(cached, now):
            self._logger.debug(f"{label}: cached page, {len(cached.cumulative_eps)} companies")
            return cached

        cumulative_eps = await self.download(market, quarter)

        if cumulative_eps == {} and quarter.is_final_on(today):
            self._logger.warning(f"{label}: empty page for a quarter whose filing deadline has passed; not cached")
            cumulative_eps = None

        if cumulative_eps is not None:
            page = QuarterEps(quarter=quarter, cumulative_eps=cumulative_eps, fetched_at=now)
            await self.save_page(market, page)
            self._logger.info(f"{label}: fetched {len(cumulative_eps)} companies")
            return page

        if cached is None:
            return None

        fetched_at = self._clock.to_market_datetime(cached.fetched_at)
        self._logger.warning(f"{label}: refresh failed, using the page fetched at {fetched_at:%Y-%m-%d %H:%M}")

        return replace(cached, refresh_failed=True)

    @override
    def is_reusable(self, page: QuarterEps, now: datetime) -> bool:
        if page.cumulative_eps and page.quarter.is_final_on(self._clock.to_trading_date(page.fetched_at)):
            return True

        return now - page.fetched_at < self._provisional_page_max_age

    @override
    async def download(self, market: MarketType, quarter: FiscalQuarter) -> dict[str, float] | None:
        label = f"MOPS {quarter} {self._market_codes[market]}"
        quarter_fields = {
            "TYPEK": self._market_codes[market],
            "year": str(quarter.year - ROC_YEAR_OFFSET),
            "season": f"{quarter.quarter:02d}",
        }

        await self.wait_for_request_slot()

        try:
            async with httpx.AsyncClient(timeout=self._mops.timeout_seconds) as client:
                response = await client.post(self._mops.eps_url, data={**self._mops.eps_form_fields, **quarter_fields})
                response.raise_for_status()
        except Exception as error:
            self._logger.warning(f"{label}: request failed: {error}")
            return None

        cumulative_eps = self.parse_cumulative_eps(response.text)

        if cumulative_eps is None:
            self._logger.warning(f"{label}: unrecognised page ({len(response.text)} bytes)")

        return cumulative_eps

    @override
    def parse_cumulative_eps(self, html: str) -> dict[str, float] | None:
        tables = BeautifulSoup(html, "lxml").find_all("table", class_="hasBorder")

        if not tables:
            return {} if self._mops.no_data_marker in html else None

        result: dict[str, float] = {}

        for table in tables:
            # Row 0 names the columns in <th> cells, wrapped with <br> inside a name, so every cell drops all whitespace.
            rows = [
                ["".join(cell.get_text().split()) for cell in row.find_all("td" if index else "th")]
                for index, row in enumerate(table.find_all("tr"))
            ]
            table_eps = self.parse_eps_table(rows)

            if table_eps is None:
                return None

            result.update(table_eps)

        return result

    @override
    def parse_eps_table(self, rows: list[list[str]]) -> dict[str, float] | None:
        header = rows[0] if rows else []
        eps_index = next((index for index, name in enumerate(header) if name.startswith(self._mops.eps_header_prefix)), None)

        if self._mops.company_id_header not in header or eps_index is None:
            return None

        id_index = header.index(self._mops.company_id_header)
        cumulative_eps: dict[str, float] = {}

        for cells in rows[1:]:
            if len(cells) != len(header):
                continue

            try:
                cumulative_eps[cells[id_index]] = float(cells[eps_index].replace(",", ""))
            except ValueError:
                continue

        return cumulative_eps

    @override
    async def wait_for_request_slot(self) -> None:
        if self._last_request_at is not None:
            await asyncio.sleep(max(0.0, self._mops.request_interval_seconds - (time.monotonic() - self._last_request_at)))

        self._last_request_at = time.monotonic()

    @override
    async def load_page(self, market: MarketType, quarter: FiscalQuarter) -> QuarterEps | None:
        async with self._db.get_session() as session:
            page = await session.get(QuarterEpsDTO, (market.value, quarter.year, quarter.quarter))
            return page.to_domain() if page is not None else None

    @override
    async def save_page(self, market: MarketType, page: QuarterEps) -> None:
        async with self._db.get_session() as session:
            await session.merge(QuarterEpsDTO.from_domain(market, page))
            await session.commit()

    @override
    async def fetch_industries(self) -> dict[str, str]:
        now = self._clock.now()

        for market in self._industry_sources:
            fetched_at = self._industries_fetched_at.get(market)

            if fetched_at is not None and now - fetched_at < self._industry_max_age:
                continue

            industries = await self.fetch_market_industries(market)

            if industries is not None:
                self._industries[market] = industries
                self._industries_fetched_at[market] = now

        return {stock_id: industry for industries in self._industries.values() for stock_id, industry in industries.items()}

    @override
    async def fetch_market_industries(self, market: MarketType) -> dict[str, str] | None:
        url, id_field = self._industry_sources[market]
        industry_field = self._mops.industry_field

        try:
            async with httpx.AsyncClient(timeout=self._mops.timeout_seconds) as client:
                response = await client.get(url)
                response.raise_for_status()
                return {
                    str(row[id_field]).strip(): str(row[industry_field]).strip()
                    for row in response.json()
                    if row.get(id_field) and row.get(industry_field)
                }
        except Exception as error:
            self._logger.warning(f"MOPS industries for {market.value} unavailable: {error}")
            return None
