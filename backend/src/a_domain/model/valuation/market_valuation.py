from __future__ import annotations

import statistics
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date

from icontract import invariant

from a_domain.model.market.ohlcv import Ohlcv
from a_domain.model.market.stock import Stock
from a_domain.model.valuation.pe_median import PeMedian
from a_domain.model.valuation.pe_not_applicable import PeNotApplicable
from a_domain.model.valuation.pe_ratio import PeRatio
from a_domain.model.valuation.scan_criteria import ScanCriteria
from a_domain.model.valuation.scan_elimination import ScanElimination
from a_domain.model.valuation.stock_valuation import StockValuation
from a_domain.model.valuation.target_pe import TargetPe
from a_domain.model.valuation.valuation_report import ValuationReport
from a_domain.model.valuation.valuation_scan import ValuationScan
from a_domain.types.enums import EliminationReason, PeNotApplicableReason


@invariant(lambda self: 0 < self.scenario_spread < 1)
@dataclass(frozen=True)
class MarketValuation:
    """Every listed and OTC stock's valuation inputs for one run, plus the scenario policy of that run."""

    valuations: Mapping[str, StockValuation]
    last_closed_session: date
    max_missed_sessions: int
    """How many weekday sessions may close after a close's session before the close is stale."""

    scenario_spread: float
    source_warnings: tuple[str, ...] = ()

    @classmethod
    def of(
        cls,
        stocks: list[Stock],
        closes: Mapping[str, Ohlcv],
        last_closed_session: date,
        max_missed_sessions: int,
        scenario_spread: float,
        source_warnings: tuple[str, ...],
    ) -> MarketValuation:
        valuations = {
            stock.stock_id: StockValuation(
                stock=stock,
                close=closes.get(stock.stock_id),
                last_closed_session=last_closed_session,
                max_missed_sessions=max_missed_sessions,
            )
            for stock in stocks
        }

        return cls(valuations, last_closed_session, max_missed_sessions, scenario_spread, source_warnings)

    def find(self, stock_id: str) -> StockValuation | None:
        return self.valuations.get(stock_id)

    def appraise(self, valuation: StockValuation, target_pe: TargetPe | None) -> ValuationReport:
        return ValuationReport.appraise(valuation, target_pe, self.scenario_spread)

    def median_pe(self, industry: str | None = None) -> PeMedian | None:
        """Median current P/E over stocks with a computable P/E and a fresh close. A reference only, never a target."""
        values = [
            pe.value
            for valuation in self.valuations.values()
            if (industry is None or valuation.stock.industry == industry)
            and valuation.close_is_fresh
            and isinstance(pe := valuation.current_pe, PeRatio)
        ]

        if not values:
            return None

        return PeMedian(value=statistics.median(values), sample_size=len(values))

    def screen(self, criteria: ScanCriteria, max_explanations: int) -> ValuationScan:
        """
        The undervalued scan's valuation step. The first failing check eliminates a stock. The scan offers at most
        `max_explanations` of its top survivors for an AI explanation.
        """
        survivors: list[ValuationReport] = []
        eliminations: list[ScanElimination] = []

        for valuation in self.valuations.values():
            report = self.appraise(valuation, criteria.target_pe)
            reason, detail = _valuation_elimination(report, criteria)

            if reason is None:
                survivors.append(report)
            else:
                eliminations.append(ScanElimination(report=report, reason=reason, detail=detail))

        return ValuationScan(
            criteria=criteria,
            survivors=ValuationScan.by_undervaluation(survivors),
            eliminations=tuple(eliminations),
            max_explanations=max_explanations,
        )


def _valuation_elimination(report: ValuationReport, criteria: ScanCriteria) -> tuple[EliminationReason | None, str]:
    if isinstance(report.fair_value, PeNotApplicable):
        return VALUATION_REASONS[report.fair_value.reason], report.fair_value.reason.label

    if not report.valuation.close_is_fresh:
        return EliminationReason.PRICE_STALE, report.valuation.price_text

    undervaluation = report.fair_value.base.undervaluation

    if undervaluation < criteria.min_undervaluation:
        return (
            EliminationReason.BELOW_MIN_UNDERVALUATION,
            f"undervaluation {undervaluation:.1%} is below {criteria.min_undervaluation:.1%}",
        )

    return None, ""


VALUATION_REASONS = {
    PeNotApplicableReason.EPS_UNAVAILABLE: EliminationReason.EPS_UNAVAILABLE,
    PeNotApplicableReason.EPS_ZERO: EliminationReason.EPS_NOT_POSITIVE,
    PeNotApplicableReason.EPS_NEGATIVE: EliminationReason.EPS_NOT_POSITIVE,
    PeNotApplicableReason.INVALID_PRICE: EliminationReason.PRICE_MISSING,
}
