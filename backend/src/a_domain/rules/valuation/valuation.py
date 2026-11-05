import math
from datetime import date

from pydantic import NonNegativeInt
from pydantic.dataclasses import dataclass

from a_domain.model.fundamentals.eps import Eps, EpsUnavailable
from a_domain.model.market.ohlcv import Ohlcv
from a_domain.model.market.stock import Stock
from a_domain.model.valuation.valuation import (
    FairPriceRange,
    PeRatio,
    ReportSection,
    StockValuation,
    ValuationExplanation,
    ValuationReport,
    ValuationScenario,
)
from a_domain.rules.collect.freshness import DailyCloseFreshnessRule, MissedSessionsRule
from a_domain.rules.fundamentals.filing import FilingDeadlineRule
from a_domain.types.enums import PeNotApplicableReason, ScenarioName
from a_domain.types.values import NonEmptyText, PositiveFiniteFloat, ProperFraction


@dataclass(frozen=True)
class StockValuationRule:
    """
    A stock's valuation before any user assumption: its current P/E, whether its close is fresh, and what is missing
    or stale. The P/E does not apply to missing or non-positive EPS, or without a valid close.
    """

    max_missed_sessions: NonNegativeInt
    """How many weekday sessions may close after the close's session before the close is stale."""

    filing_deadline_rule: FilingDeadlineRule
    """Names the filing deadline in the warning for a quarter the EPS lacks."""

    def apply(self, stock: Stock, close: Ohlcv | None, last_closed_session: date) -> StockValuation:
        is_fresh = close is not None and DailyCloseFreshnessRule(self.max_missed_sessions).apply(close.ts.date(), last_closed_session)

        return StockValuation(
            stock=stock,
            close=close,
            current_pe=self._current_pe(stock.eps, close),
            close_is_fresh=is_fresh,
            warnings=(*self._eps_warnings(stock.eps), *self._close_warnings(close, is_fresh, last_closed_session)),
        )

    def _current_pe(self, eps: Eps | EpsUnavailable, close: Ohlcv | None) -> PeRatio | PeNotApplicableReason:
        if isinstance(eps, EpsUnavailable):
            return PeNotApplicableReason.EPS_UNAVAILABLE

        if eps.value == 0:
            return PeNotApplicableReason.EPS_ZERO

        if eps.value < 0:
            return PeNotApplicableReason.EPS_NEGATIVE

        if close is None or not math.isfinite(close.close) or close.close <= 0:
            return PeNotApplicableReason.INVALID_PRICE

        return PeRatio(price=close.close, eps=eps.value)

    def _eps_warnings(self, eps: Eps | EpsUnavailable) -> tuple[str, ...]:
        if isinstance(eps, EpsUnavailable):
            return (eps.describe(),)

        not_included = tuple(
            f"{quarter} filings are not included (filing deadline {self.filing_deadline_rule.apply(quarter)}; the company has not "
            f"filed yet or the data could not be fetched), so this run uses the TTM EPS through {eps.period_end}"
            for quarter in eps.newer_quarters
        )

        if eps.value == 0:
            return (*not_included, "The TTM EPS is 0, so the P/E cannot be computed and no P/E valuation is made")

        if eps.value < 0:
            return (*not_included, f"The TTM EPS is {eps.value:.2f} (a loss), so the P/E does not apply and no fair price is computed")

        return not_included

    def _close_warnings(self, close: Ohlcv | None, is_fresh: bool, last_closed_session: date) -> tuple[str, ...]:
        if close is None:
            return ("No valid close: no trade in the latest session, or the exchange data is missing",)

        if is_fresh:
            return ()

        session = close.ts.date()
        missed = MissedSessionsRule().apply(session, last_closed_session)

        return (
            f"Stale price: closed on {session}, and {missed} sessions have closed since (last closed session {last_closed_session})",
        )


@dataclass(frozen=True)
class AppraisalRule:
    """
    A stock valued at the user's target P/E: one scenario at the target, and one at the configured spread below and
    above it. A stock whose P/E does not apply gets no scenarios, whatever the target.
    """

    scenario_spread: ProperFraction

    def apply(self, valuation: StockValuation, target_pe: PositiveFiniteFloat | None) -> ValuationReport:
        pe = valuation.current_pe

        if isinstance(pe, PeNotApplicableReason):
            return ValuationReport(valuation=valuation, target_pe=target_pe, fair_value=pe)

        if target_pe is None:
            raise ValueError("A computable P/E needs a target P/E")

        return ValuationReport(valuation=valuation, target_pe=target_pe, fair_value=self._fair_price_range(pe, target_pe))

    def _fair_price_range(self, pe: PeRatio, target_pe: PositiveFiniteFloat) -> FairPriceRange:
        spread = self.scenario_spread

        def around_base(name: ScenarioName, factor: float, sign: str) -> ValuationScenario:
            assumption = f"base × (1 {sign} {spread:.0%}), from the valuation.scenario_spread setting"
            return ValuationScenario(name=name, target_pe=target_pe * factor, assumption=assumption, pe=pe)

        return FairPriceRange(
            conservative=around_base(ScenarioName.CONSERVATIVE, 1 - spread, "−"),
            base=ValuationScenario(name=ScenarioName.BASE, target_pe=target_pe, assumption="the target P/E the user entered", pe=pe),
            optimistic=around_base(ScenarioName.OPTIMISTIC, 1 + spread, "+"),
        )


@dataclass(frozen=True)
class FactSectionsRule:
    """Price, EPS, current and target P/E, fair prices and gaps: the AI prompt's facts and the printed report alike."""

    undervaluation_formula: NonEmptyText

    def apply(self, report: ValuationReport) -> tuple[ReportSection, ...]:
        valuation = report.valuation

        return (
            ReportSection("Current price", (valuation.price_text,)),
            ReportSection("EPS and reporting period", (valuation.eps.describe(),)),
            ReportSection("Current P/E", (valuation.pe_text,)),
            ReportSection("Target P/E", (self._target_text(report),)),
            ReportSection("Fair price (Valuation based on a specified P/E)", self._fair_price_lines(report.fair_value)),
            ReportSection("Overvaluation / undervaluation", self._gap_lines(report.fair_value)),
        )

    def _target_text(self, report: ValuationReport) -> str:
        if isinstance(report.fair_value, FairPriceRange):
            return f"{report.fair_value.base.target_pe:.2f}x (user input, used for this analysis only)"

        reason = report.fair_value.label

        if report.target_pe is None:
            return f"not set ({reason})"

        return f"{report.target_pe:.2f}x (user input; not applied: {reason})"

    def _fair_price_lines(self, fair_value: FairPriceRange | PeNotApplicableReason) -> tuple[str, ...]:
        if isinstance(fair_value, PeNotApplicableReason):
            return (f"Not applicable: {fair_value.label} (the P/E model is not used when EPS ≤ 0 or data is insufficient)",)

        return tuple(
            f"{scenario.name.label} {scenario.fair_price:,.2f} TWD | P/E {scenario.target_pe:.2f}x | assumption: {scenario.assumption}"
            for scenario in fair_value
        )

    def _gap_lines(self, fair_value: FairPriceRange | PeNotApplicableReason) -> tuple[str, ...]:
        if isinstance(fair_value, PeNotApplicableReason):
            return ("Not applicable",)

        lines = [
            f"{scenario.name.label} gap {scenario.gap:+,.2f} TWD, {self._over_or_under(scenario.undervaluation)}"
            for scenario in fair_value
        ]

        return (*lines, self.undervaluation_formula)

    def _over_or_under(self, undervaluation: float) -> str:
        if undervaluation > 0:
            return f"undervalued by {undervaluation:.1%}"

        if undervaluation < 0:
            return f"overvalued by {-undervaluation:.1%}"

        return "the price equals the fair price"


@dataclass(frozen=True)
class ExplanationSectionsRule:
    """Every section of the valuation explanation, in order, in every case: EPS missing, EPS ≤ 0, AI failed."""

    fact_sections_rule: FactSectionsRule
    low_pe_caveat: NonEmptyText
    ai_not_provided: NonEmptyText
    not_investment_advice: NonEmptyText

    def apply(self, explanation: ValuationExplanation) -> tuple[ReportSection, ...]:
        report = explanation.report
        risks = explanation.pe_derating_risks or (self.ai_not_provided,)

        if report.appears_undervalued:
            risks = (*risks, self.low_pe_caveat)

        warnings = list(report.valuation.warnings)

        if not report.stock.articles:
            warnings.append("No related news was found, so the AI explanation relies on the valuation numbers only")

        warnings.extend(f"AI: {gap}" for gap in explanation.data_gaps)

        return (
            *self.fact_sections_rule.apply(report),
            ReportSection("Factors that may support a higher P/E", explanation.higher_pe_factors or (self.ai_not_provided,)),
            ReportSection("Risks that may lower the P/E", risks),
            ReportSection("Insufficient data warnings", tuple(warnings) or ("none",)),
            ReportSection("Not investment advice", (self.not_investment_advice,)),
            ReportSection("AI summary", (explanation.summary or self.ai_not_provided,)),
        )
