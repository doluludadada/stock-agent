from dataclasses import dataclass

from a_domain.model.fundamentals.monthly_revenue import MonthlyRevenue
from a_domain.model.fundamentals.quarter_financials import QuarterFinancials


@dataclass(frozen=True)
class StockFinancials:
    """A stock page's financials, as Pipeline.load_financials returns them: what the open-data archive holds of the stock."""

    quarters: list[QuarterFinancials]
    """Each quarter's figures as the open-data archive holds them, oldest first."""

    monthly_revenues: list[MonthlyRevenue]
    """Each month's revenue as the open-data archive holds it, oldest first."""
