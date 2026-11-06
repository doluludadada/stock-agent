from datetime import date
from typing import Annotated

from pydantic import Field, FiniteFloat
from pydantic.dataclasses import dataclass

from a_domain.types.enums import MarketType


@dataclass(frozen=True)
class MonthlyRevenue:
    """
    One company's revenue of one month, as the TWSE or TPEX OpenAPI's monthly revenue summary serves it, under the
    Gregorian year and the month, with the day the exchange served it. Revenues are in thousands of TWD and changes in
    percent; a figure the summary leaves blank is None. The company's name, industry and note are as served.
    """

    stock_id: str
    year: int
    month: Annotated[int, Field(ge=1, le=12)]
    market: MarketType
    served_date: date
    company_name: str
    industry: str
    revenue: FiniteFloat | None
    previous_month_revenue: FiniteFloat | None
    last_year_revenue: FiniteFloat | None
    """The revenue of the same month a year before."""

    month_over_month_percent: FiniteFloat | None
    year_over_year_percent: FiniteFloat | None
    cumulative_revenue: FiniteFloat | None
    """The revenue of the year to the month's end."""

    last_year_cumulative_revenue: FiniteFloat | None
    cumulative_year_over_year_percent: FiniteFloat | None
    note: str

    @property
    def period_label(self) -> str:
        return f"{self.year}-{self.month:02d}"

    def describe(self) -> str:
        """The only text form of a month's revenue. It names the month and the unit, and leaves out what is None."""
        figures = [
            ("revenue", self.revenue, ",.0f", ""),
            ("month over month", self.month_over_month_percent, "+.2f", "%"),
            ("year over year", self.year_over_year_percent, "+.2f", "%"),
            ("year to date", self.cumulative_revenue, ",.0f", ""),
            ("year to date year over year", self.cumulative_year_over_year_percent, "+.2f", "%"),
        ]
        described = ", ".join(f"{name} {value:{spec}}{unit}" for name, value, spec, unit in figures if value is not None)
        return f"{self.period_label} (revenues in TWD thousand): {described or 'no figure served'}"
