from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, replace

from icontract import require

from a_domain.model.valuation.scan_criteria import ScanCriteria
from a_domain.model.valuation.scan_elimination import ScanElimination
from a_domain.model.valuation.valuation_report import ValuationReport
from a_domain.types.enums import EliminationReason, ScanStep


@dataclass(frozen=True)
class ValuationScan:
    """
    The undervalued scan's funnel: valuation, then technical. Survivors passed every step run so far, sorted by undervaluation.

    It carries no action or signal: a low P/E never becomes a BUY here.
    """

    criteria: ScanCriteria
    survivors: tuple[ValuationReport, ...]
    eliminations: tuple[ScanElimination, ...]
    max_explanations: int
    """How many of the top survivors the scan offers for an AI explanation: each is one AI call."""

    technical_strategy_id: str | None = None

    @staticmethod
    def by_undervaluation(reports: list[ValuationReport]) -> tuple[ValuationReport, ...]:
        """Most undervalued first; ties in stock id order."""
        return tuple(sorted(reports, key=lambda report: (-(report.undervaluation or 0.0), report.stock.stock_id)))

    @require(lambda self: self.technical_strategy_id is None, "The technical step runs once")
    def after_technical_step(self, strategy_id: str) -> ValuationScan:
        """Reads the TechnicalReport the technical filter wrote on each survivor's stock."""
        survivors: list[ValuationReport] = []
        eliminations = list(self.eliminations)

        for report in self.survivors:
            technical_report = report.stock.technical_report

            if technical_report is None:
                eliminations.append(ScanElimination(report, EliminationReason.NO_PRICE_HISTORY, ""))
            elif not technical_report.passed:
                detail = ", ".join(technical_report.hard_failures)
                eliminations.append(ScanElimination(report, EliminationReason.TECHNICAL_HARD_FAILURE, detail))
            else:
                survivors.append(report)

        return replace(self, survivors=tuple(survivors), eliminations=tuple(eliminations), technical_strategy_id=strategy_id)

    @property
    def explanation_candidates(self) -> tuple[ValuationReport, ...]:
        """The most undervalued survivors, at most `max_explanations` of them."""
        return self.survivors[: self.max_explanations]

    @property
    def valuation_survivors(self) -> tuple[ValuationReport, ...]:
        """Stocks that passed the valuation step, whatever happened at the technical step."""
        technical = [elimination.report for elimination in self.technical_eliminations.values()]

        return self.by_undervaluation([*self.survivors, *technical])

    @property
    def technical_eliminations(self) -> dict[str, ScanElimination]:
        return {
            elimination.report.stock.stock_id: elimination
            for elimination in self.eliminations
            if elimination.reason.step == ScanStep.TECHNICAL
        }

    def elimination_counts(self, step: ScanStep) -> Counter[EliminationReason]:
        return Counter(elimination.reason for elimination in self.eliminations if elimination.reason.step == step)
