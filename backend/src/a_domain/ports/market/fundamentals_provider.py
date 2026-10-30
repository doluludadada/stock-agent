from collections.abc import Collection
from typing import Protocol

from a_domain.model.fundamentals.eps import EpsFilings, FiscalQuarter


class IFundamentalsProvider(Protocol):
    """
    Filed financial statements for every listed and OTC company.

    It returns raw cumulative EPS per quarter; the TTM rule lives in the domain.
    Neither method raises: a quarter that cannot be fetched maps to None, a quarter whose refresh failed keeps its
    last fetched page with refresh_failed set, and missing industries are absent.
    """

    async def fetch_cumulative_eps(self, quarters: Collection[FiscalQuarter]) -> EpsFilings: ...

    async def fetch_industries(self) -> dict[str, str]:
        """stock_id -> industry (產業別)."""
        ...
