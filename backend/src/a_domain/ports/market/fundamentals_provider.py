from collections.abc import Collection
from datetime import date
from typing import Protocol

from a_domain.model.fundamentals.monthly_revenue import MonthlyRevenue
from a_domain.rules.fundamentals.trailing_eps import EpsFilings, QuarterEps
from a_domain.types.enums import MarketType
from a_domain.types.values import FiscalQuarter


class IFundamentalsProvider(Protocol):
    """
    Filed financial statements for every listed and OTC company, and their monthly revenue of any past month.

    It returns raw cumulative EPS per quarter; the TTM rule lives in the domain. Each market's page for a quarter is
    cached, reused while it is final or recent, and downloaded otherwise.
    No method raises: a quarter or a page that cannot be fetched maps to None, and a page whose refresh failed is the
    last one fetched with refresh_failed set.
    """

    async def fetch_monthly_revenues(self, market: MarketType, year: int, month: int) -> list[MonthlyRevenue] | None:
        """
        The market's monthly revenue summary of one month, which MOPS serves for any past month (sources.mops), each row
        read as the OpenAPI's summary of the latest month is (ITaiwanStockProvider.fetch_monthly_revenues). It is not
        cached here: the open-data archive keeps it. None when the request fails or the answer is no such summary.
        """
        ...

    async def fetch_cumulative_eps(self, quarters: Collection[FiscalQuarter]) -> EpsFilings:
        """Every market's page for each quarter, merged. A quarter is None when any market's page is missing."""
        ...

    async def fetch_page(self, market: MarketType, quarter: FiscalQuarter, today: date) -> QuarterEps | None:
        """The cached page while it is reusable, else a fresh download, else the cached page marked refresh_failed."""
        ...

    async def load_page(self, market: MarketType, quarter: FiscalQuarter) -> QuarterEps | None: ...
