from pydantic import FiniteFloat
from pydantic.dataclasses import dataclass

from a_domain.types.values import FiscalQuarter


@dataclass(frozen=True)
class QuarterFinancials:
    """
    One company's figures of one quarter, as its balance sheet, its income statement and its EPS statistics in the TWSE
    or TPEX OpenAPI give them, in thousands of TWD: the income figures run from the year's start to the quarter's end,
    the balance figures stand at the quarter's end, and the EPS and the book value per share are in TWD. A figure its
    industry format does not report, or a statement the archive does not hold, is None.
    """

    quarter: FiscalQuarter
    revenue: FiniteFloat | None = None
    gross_profit: FiniteFloat | None = None
    operating_income: FiniteFloat | None = None
    net_income: FiniteFloat | None = None
    """The net income attributable to the owners of the parent."""

    eps: FiniteFloat | None = None
    """The basic EPS of the year to the quarter's end."""

    total_assets: FiniteFloat | None = None
    total_liabilities: FiniteFloat | None = None
    equity: FiniteFloat | None = None
    """The equity attributable to the owners of the parent."""

    book_value_per_share: FiniteFloat | None = None

    def describe(self) -> str:
        """The only text form of a quarter's figures. It names the period and each unit, and leaves out what is None."""
        sections = [
            (
                "income of the year to its end in TWD thousand",
                ",.0f",
                [
                    ("revenue", self.revenue),
                    ("gross profit", self.gross_profit),
                    ("operating income", self.operating_income),
                    ("net income attributable to the parent", self.net_income),
                ],
            ),
            (
                "balance at its end in TWD thousand",
                ",.0f",
                [
                    ("total assets", self.total_assets),
                    ("total liabilities", self.total_liabilities),
                    ("equity attributable to the parent", self.equity),
                ],
            ),
            ("per share in TWD", ",.2f", [("basic EPS", self.eps), ("book value per share", self.book_value_per_share)]),
        ]
        described = [
            f"{title}: " + ", ".join(f"{name} {value:{spec}}" for name, value in figures if value is not None)
            for title, spec, figures in sections
            if any(value is not None for _, value in figures)
        ]
        return f"{self.quarter}: " + ("; ".join(described) or "no figure archived")
