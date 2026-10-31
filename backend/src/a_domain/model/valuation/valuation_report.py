from __future__ import annotations

from dataclasses import dataclass

from a_domain.model.market.stock import Stock
from a_domain.model.valuation.fair_price_range import FairPriceRange
from a_domain.model.valuation.pe_not_applicable import PeNotApplicable
from a_domain.model.valuation.pe_ratio import PeRatio
from a_domain.model.valuation.report_section import ReportSection
from a_domain.model.valuation.stock_valuation import StockValuation
from a_domain.model.valuation.target_pe import TargetPe
from a_domain.model.valuation.valuation_scenario import ValuationScenario

LABEL = "Valuation based on a specified P/E"


UNDERVALUATION_FORMULA = (
    "Undervaluation = (fair price − current price) ÷ current price; positive is undervalued, negative is overvalued"
)


@dataclass(frozen=True)
class ValuationReport:
    """A stock valued at the user's target P/E. Scenarios exist exactly when the current P/E is computable."""

    valuation: StockValuation
    target_pe: TargetPe | None
    fair_value: FairPriceRange | PeNotApplicable

    @classmethod
    def appraise(cls, valuation: StockValuation, target_pe: TargetPe | None, spread: float) -> ValuationReport:
        match valuation.current_pe:
            case PeNotApplicable() as not_applicable:
                return cls(valuation=valuation, target_pe=target_pe, fair_value=not_applicable)
            case PeRatio() as pe:
                if target_pe is None:
                    raise ValueError("A computable P/E needs a target P/E")

                return cls(valuation=valuation, target_pe=target_pe, fair_value=FairPriceRange.of(pe, target_pe, spread))

    @property
    def stock(self) -> Stock:
        return self.valuation.stock

    @property
    def base(self) -> ValuationScenario | None:
        """The scenario at the user's target P/E, or None when no fair price applies."""
        return self.fair_value.base if isinstance(self.fair_value, FairPriceRange) else None

    @property
    def undervaluation(self) -> float | None:
        return self.base.undervaluation if self.base is not None else None

    @property
    def appears_undervalued(self) -> bool:
        return self.undervaluation is not None and self.undervaluation > 0

    def fact_sections(self) -> tuple[ReportSection, ...]:
        """Price, EPS, current and target P/E, fair prices and gaps: the AI prompt's facts and the printed report alike."""
        valuation = self.valuation

        return (
            ReportSection("Current price", (valuation.price_text,)),
            ReportSection("EPS and reporting period", (valuation.eps.describe(),)),
            ReportSection("Current P/E", (valuation.pe_text,)),
            ReportSection("Target P/E", (self._target_text(),)),
            ReportSection(f"Fair price ({LABEL})", self._fair_price_lines()),
            ReportSection("Overvaluation / undervaluation", self._gap_lines()),
        )

    def _target_text(self) -> str:
        if isinstance(self.fair_value, FairPriceRange):
            return f"{self.fair_value.base.target_pe:.2f}x (user input, used for this analysis only)"

        reason = self.fair_value.reason.label

        if self.target_pe is None:
            return f"not set ({reason})"

        return f"{self.target_pe.value:.2f}x (user input; not applied: {reason})"

    def _fair_price_lines(self) -> tuple[str, ...]:
        if isinstance(self.fair_value, PeNotApplicable):
            return (
                f"Not applicable: {self.fair_value.reason.label} (the P/E model is not used when EPS ≤ 0 or data is insufficient)",
            )

        return tuple(
            f"{scenario.name.label} {scenario.fair_price:,.2f} TWD | P/E {scenario.target_pe:.2f}x | assumption: {scenario.assumption}"
            for scenario in self.fair_value
        )

    def _gap_lines(self) -> tuple[str, ...]:
        if isinstance(self.fair_value, PeNotApplicable):
            return ("Not applicable",)

        lines = [
            f"{scenario.name.label} gap {scenario.gap:+,.2f} TWD, {_over_or_under(scenario.undervaluation)}"
            for scenario in self.fair_value
        ]

        return (*lines, UNDERVALUATION_FORMULA)


def _over_or_under(undervaluation: float) -> str:
    if undervaluation > 0:
        return f"undervalued by {undervaluation:.1%}"

    if undervaluation < 0:
        return f"overvalued by {-undervaluation:.1%}"

    return "the price equals the fair price"
