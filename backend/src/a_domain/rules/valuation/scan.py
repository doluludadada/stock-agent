from pydantic import PositiveInt
from pydantic.dataclasses import dataclass

from a_domain.model.valuation.scan import MarketValuation, ScanCriteria, ScanElimination, ValuationScan
from a_domain.model.valuation.valuation import ValuationReport
from a_domain.rules.valuation.valuation import AppraisalRule
from a_domain.types.enums import EliminationReason, PeNotApplicableReason


@dataclass(frozen=True)
class ValuationStepRule:
    """
    The undervalued scan's valuation step: every stock valued at the criteria's target P/E. The first failing check
    eliminates a stock: its P/E does not apply, its close is stale, or it is less undervalued than the criteria ask.
    """

    appraisal_rule: AppraisalRule
    max_explanations: PositiveInt
    """How many of the top survivors the scan offers for an AI explanation: each is one AI call."""

    def apply(self, market: MarketValuation, criteria: ScanCriteria) -> ValuationScan:
        survivors: list[ValuationReport] = []
        eliminations: list[ScanElimination] = []

        for valuation in market.valuations.values():
            report = self.appraisal_rule.apply(valuation, criteria.target_pe)
            elimination = self._elimination(report, criteria.min_undervaluation)

            if elimination is None:
                survivors.append(report)
            else:
                eliminations.append(elimination)

        return ValuationScan(
            criteria=criteria,
            survivors=ValuationScan.by_undervaluation(survivors),
            eliminations=tuple(eliminations),
            max_explanations=self.max_explanations,
        )

    def _elimination(self, report: ValuationReport, min_undervaluation: float) -> ScanElimination | None:
        if isinstance(report.fair_value, PeNotApplicableReason):
            return ScanElimination(report, report.fair_value.elimination_reason, report.fair_value.label)

        if not report.valuation.close_is_fresh:
            return ScanElimination(report, EliminationReason.PRICE_STALE, report.valuation.price_text)

        undervaluation = report.fair_value.base.undervaluation

        if undervaluation < min_undervaluation:
            detail = f"undervaluation {undervaluation:.1%} is below {min_undervaluation:.1%}"
            return ScanElimination(report, EliminationReason.BELOW_MIN_UNDERVALUATION, detail)

        return None
