import asyncio
import csv
import io
from collections.abc import Collection
from dataclasses import replace
from datetime import date, datetime, timedelta
from typing import override

import httpx
from bs4 import BeautifulSoup

from a_domain.model.fundamentals.monthly_revenue import MonthlyRevenue
from a_domain.ports.market.fundamentals_provider import IFundamentalsProvider
from a_domain.ports.market.taiwan_stock_provider import ITaiwanStockProvider
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.system.market_clock import IMarketClock
from a_domain.rules.fundamentals.filing import FilingDeadlineRule, FinalFilingsRule
from a_domain.rules.fundamentals.trailing_eps import EpsFilings, QuarterEps
from a_domain.types.enums import MarketType
from a_domain.types.values import FiscalQuarter
from b_application.config.sources_config import MopsSources
from c_infrastructure.database.db_connector import DatabaseConnector
from c_infrastructure.database.models.quarter_eps_dto import QuarterEpsDTO
from c_infrastructure.market.exchange_text import ROC_YEAR_OFFSET, parse_number
from c_infrastructure.request_pace import HostPace


class MopsFundamentalsProvider(IFundamentalsProvider):
    """
    Cumulative EPS from the MOPS bulk income statements (one page per market and quarter), cached in the database, and the
    monthly revenue summary of a past month (one CSV per market and month), read with the exchange listing's parser.

    A quarter's cached page is final, and never fetched again, once it was fetched after the quarter's last filing
    deadline plus grace and is not empty. Any other page is reused for `provisional_page_max_age_hours`. Each request
    waits its turn on `pace`, the one pace for every request to MOPS, which the wiring keeps in the database.
    """

    def __init__(
        self,
        db: DatabaseConnector,
        market_clock: IMarketClock,
        mops: MopsSources,
        listing: ITaiwanStockProvider,
        logger: ILoggingProvider,
        write_lock: asyncio.Lock,
        pace: HostPace,
    ) -> None:
        self._db = db
        self._listing = listing
        # One page save at a time per process, every runtime's: two runs merging the same quarter at once would both insert it.
        self._write_lock = write_lock
        self._mops = mops
        self._market_codes = {MarketType.TWSE: mops.twse_market_code, MarketType.TPEX: mops.tpex_market_code}
        self._provisional_page_max_age = timedelta(hours=mops.provisional_page_max_age_hours)
        self._final_filings_rule = FinalFilingsRule(
            filing_deadline_rule=FilingDeadlineRule(mops.filing_deadlines), grace_days=mops.filing_grace_days
        )
        self._clock = market_clock
        self._logger = logger
        self._pace = pace

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

        if cached is not None and is_reusable(cached, now, self._final_filings_rule, self._clock, self._provisional_page_max_age):
            self._logger.debug(f"{label}: cached page, {len(cached.cumulative_eps)} companies")
            return cached

        cumulative_eps = await download_cumulative_eps(self._market_codes[market], quarter, self._mops, self._pace, self._logger)

        if cumulative_eps == {} and self._final_filings_rule.apply(quarter, today):
            self._logger.warning(f"{label}: empty page for a quarter whose filing deadline has passed; not cached")
            cumulative_eps = None

        if cumulative_eps is not None:
            page = QuarterEps(quarter=quarter, cumulative_eps=cumulative_eps, fetched_at=now)
            await save_page(market, page, self._write_lock, self._db)
            self._logger.info(f"{label}: fetched {len(cumulative_eps)} companies")
            return page

        if cached is None:
            return None

        fetched_at = self._clock.to_market_datetime(cached.fetched_at)
        self._logger.warning(f"{label}: refresh failed, using the page fetched at {fetched_at:%Y-%m-%d %H:%M}")

        return replace(cached, refresh_failed=True)

    @override
    async def fetch_monthly_revenues(self, market: MarketType, year: int, month: int) -> list[MonthlyRevenue] | None:
        code = self._market_codes[market]
        url = self._mops.monthly_revenue_url.format(market_code=code, roc_year=year - ROC_YEAR_OFFSET, month=month)
        await self._pace.wait(self._mops.request_interval_seconds)

        try:
            async with httpx.AsyncClient(timeout=self._mops.timeout_seconds) as client:
                response = await client.get(url)
                response.raise_for_status()
        except Exception as error:
            self._logger.warning(f"MOPS revenue {year}-{month:02d} {code}: request failed: {type(error).__name__}: {error}")
            return None

        rows = csv.DictReader(io.StringIO(response.content.decode("utf-8-sig", errors="replace")))
        revenues = [revenue for row in rows if (revenue := self._listing.parse_monthly_revenue(row, market)) is not None]
        served = [revenue for revenue in revenues if (revenue.year, revenue.month) == (year, month)]

        if not served:
            self._logger.warning(f"MOPS revenue {year}-{month:02d} {code}: no summary of that month ({len(response.content)} bytes)")
            return None

        self._logger.info(f"MOPS revenue {year}-{month:02d} {code}: {len(served)} companies")
        return served

    @override
    async def load_page(self, market: MarketType, quarter: FiscalQuarter) -> QuarterEps | None:
        async with self._db.get_session() as session:
            page = await session.get(QuarterEpsDTO, (market.value, quarter.year, quarter.quarter))
            return page.to_domain() if page is not None else None


def is_reusable(
    page: QuarterEps, now: datetime, final_filings_rule: FinalFilingsRule, clock: IMarketClock, provisional_page_max_age: timedelta
) -> bool:
    """A non-empty page fetched once its quarter was final is reused for good; any other page only while recent."""
    if page.cumulative_eps and final_filings_rule.apply(page.quarter, clock.to_trading_date(page.fetched_at)):
        return True

    return now - page.fetched_at < provisional_page_max_age


async def download_cumulative_eps(
    market_code: str, quarter: FiscalQuarter, mops: MopsSources, pace: HostPace, logger: ILoggingProvider
) -> dict[str, float] | None:
    """One request for the page: {} when the quarter has no filings yet, None when the request or the page fails."""
    label = f"MOPS {quarter} {market_code}"
    quarter_fields = {"TYPEK": market_code, "year": str(quarter.year - ROC_YEAR_OFFSET), "season": f"{quarter.quarter:02d}"}

    await pace.wait(mops.request_interval_seconds)

    try:
        async with httpx.AsyncClient(timeout=mops.timeout_seconds) as client:
            response = await client.post(mops.eps_url, data={**mops.eps_form_fields, **quarter_fields})
            response.raise_for_status()
    except Exception as error:
        logger.warning(f"{label}: request failed: {error}")
        return None

    cumulative_eps = parse_cumulative_eps(response.text, mops)

    if cumulative_eps is None:
        logger.warning(f"{label}: unrecognised page ({len(response.text)} bytes)")

    return cumulative_eps


def parse_cumulative_eps(html: str, mops: MopsSources) -> dict[str, float] | None:
    """
    Cumulative basic EPS per company from one page.

    {} when the season has no filings yet. None for a page that is neither (an error or throttle page), or a table
    missing the company-id or EPS header, so a format change fails the quarter instead of returning partial data.
    """
    tables = BeautifulSoup(html, "lxml").find_all("table", class_="hasBorder")

    if not tables:
        return {} if mops.no_data_marker in html else None

    result: dict[str, float] = {}

    for table in tables:
        # Row 0 names the columns in <th> cells, wrapped with <br> inside a name, so every cell drops all whitespace.
        rows = [
            ["".join(cell.get_text().split()) for cell in row.find_all("td" if index else "th")]
            for index, row in enumerate(table.find_all("tr"))
        ]
        table_eps = parse_eps_table(rows, mops)

        if table_eps is None:
            return None

        result.update(table_eps)

    return result


def parse_eps_table(rows: list[list[str]], mops: MopsSources) -> dict[str, float] | None:
    """One table's EPS per company from its cell texts, header row first. None without a company-id or EPS column."""
    header = rows[0] if rows else []
    eps_index = next((index for index, name in enumerate(header) if name.startswith(mops.eps_header_prefix)), None)

    if mops.company_id_header not in header or eps_index is None:
        return None

    id_index = header.index(mops.company_id_header)
    cumulative_eps: dict[str, float] = {}

    for cells in rows[1:]:
        if len(cells) != len(header):
            continue

        if (eps := parse_number(cells[eps_index])) is not None:
            cumulative_eps[cells[id_index]] = eps

    return cumulative_eps


async def save_page(market: MarketType, page: QuarterEps, write_lock: asyncio.Lock, db: DatabaseConnector) -> None:
    async with write_lock, db.get_session() as session:
        await session.merge(QuarterEpsDTO.from_domain(market, page))
        await session.commit()
