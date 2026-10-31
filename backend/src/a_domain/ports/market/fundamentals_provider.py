from collections.abc import Collection
from typing import Protocol

from a_domain.model.fundamentals.fiscal_quarter import FiscalQuarter
from a_domain.model.fundamentals.quarter_eps import EpsFilings


class IFundamentalsProvider(Protocol):
    """
    Filed financial statements for every listed and OTC company.

    It returns raw cumulative EPS per quarter; the TTM rule lives in the domain.
    Neither method raises: a quarter that cannot be fetched maps to None, a quarter whose refresh failed keeps its
    last fetched page with refresh_failed set, and missing industries are absent.
    """

    async def fetch_cumulative_eps(self, quarters: Collection[FiscalQuarter]) -> EpsFilings: ...

    async def fetch_industries(self) -> dict[str, str]:
        """stock_id -> industry name, as MOPS reports it."""
        ...
