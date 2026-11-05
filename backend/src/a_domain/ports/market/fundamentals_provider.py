from collections.abc import Collection
from datetime import date, datetime
from typing import Protocol

from a_domain.rules.fundamentals.trailing_eps import EpsFilings, QuarterEps
from a_domain.types.enums import MarketType
from a_domain.types.values import FiscalQuarter


class IFundamentalsProvider(Protocol):
    """
    Filed financial statements for every listed and OTC company.

    It returns raw cumulative EPS per quarter; the TTM rule lives in the domain. Each market's page for a quarter is
    cached, reused while it is final or recent, and downloaded otherwise.
    No method raises: a quarter or a page that cannot be fetched maps to None, a page whose refresh failed is the last
    one fetched with refresh_failed set, and missing industries are absent.
    """

    async def fetch_cumulative_eps(self, quarters: Collection[FiscalQuarter]) -> EpsFilings:
        """Every market's page for each quarter, merged. A quarter is None when any market's page is missing."""
        ...

    async def fetch_page(self, market: MarketType, quarter: FiscalQuarter, today: date) -> QuarterEps | None:
        """The cached page while it is reusable, else a fresh download, else the cached page marked refresh_failed."""
        ...

    def is_reusable(self, page: QuarterEps, now: datetime) -> bool:
        """A non-empty page fetched once its quarter was final is reused for good; any other page only while recent."""
        ...

    async def download(self, market: MarketType, quarter: FiscalQuarter) -> dict[str, float] | None:
        """One request for the page: {} when the quarter has no filings yet, None when the request or the page fails."""
        ...

    def parse_cumulative_eps(self, html: str) -> dict[str, float] | None:
        """
        Cumulative basic EPS per company from one page.

        {} when the season has no filings yet. None for a page that is neither (an error or throttle page), or a table
        missing the company-id or EPS header, so a format change fails the quarter instead of returning partial data.
        """
        ...

    def parse_eps_table(self, rows: list[list[str]]) -> dict[str, float] | None:
        """One table's EPS per company from its cell texts, header row first. None without a company-id or EPS column."""
        ...

    async def wait_for_request_slot(self) -> None:
        """Returns once enough time has passed since the previous request to the shared public service."""
        ...

    async def load_page(self, market: MarketType, quarter: FiscalQuarter) -> QuarterEps | None: ...

    async def save_page(self, market: MarketType, page: QuarterEps) -> None: ...

    async def fetch_industries(self) -> dict[str, str]:
        """stock_id -> industry name, every market merged. A market's list is reused until it is old."""
        ...

    async def fetch_market_industries(self, market: MarketType) -> dict[str, str] | None:
        """
        One market's stock_id -> industry name from its company profiles, or None when its feed fails. A company whose
        industry code has no name in the settings is absent.
        """
        ...
