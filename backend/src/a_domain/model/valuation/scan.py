from __future__ import annotations

import math
import statistics
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import date
from enum import StrEnum, auto

from icontract import invariant, require

from a_domain.model.market.ohlcv import Ohlcv
from a_domain.model.market.stock import Stock
from a_domain.model.valuation.valuation import (
    PeNotApplicable,
    PeNotApplicableReason,
    PeRatio,
    StockValuation,
    TargetPe,
    ValuationReport,
)


@dataclass(frozen=True)
class PeMedian:
    value: float
    sample_size: int


@invariant(lambda self: 0 < self.scenario_spread < 1)
@dataclass(frozen=True)
class MarketValuation:
    """Every listed and OTC stock's valuation inputs for one run, plus the scenario policy of that run."""

    valuations: Mapping[str, StockValuation]
    last_closed_session: date
    scenario_spread: float
    source_warnings: tuple[str, ...] = ()

    @classmethod
    def of(
        cls,
        stocks: list[Stock],
        closes: Mapping[str, Ohlcv],
        last_closed_session: date,
        scenario_spread: float,
        source_warnings: tuple[str, ...],
    ) -> MarketValuation:
        valuations = {
            stock.stock_id: StockValuation(stock=stock, close=closes.get(stock.stock_id), last_closed_session=last_closed_session)
            for stock in stocks
        }

        return cls(valuations, last_closed_session, scenario_spread, source_warnings)

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

    def screen(self, criteria: ScanCriteria) -> ValuationScan:
        """US-108: the valuation step. The first failing check eliminates a stock."""
        survivors: list[ValuationReport] = []
        eliminations: list[ScanElimination] = []

        for valuation in self.valuations.values():
            report = self.appraise(valuation, criteria.target_pe)
            reason, detail = _valuation_elimination(report, criteria)

            if reason is None:
                survivors.append(report)
            else:
                eliminations.append(ScanElimination(report=report, reason=reason, detail=detail))

        return ValuationScan(criteria=criteria, survivors=_by_undervaluation(survivors), eliminations=tuple(eliminations))


def _valuation_elimination(report: ValuationReport, criteria: ScanCriteria) -> tuple[EliminationReason | None, str]:
    if isinstance(report.fair_value, PeNotApplicable):
        return VALUATION_REASONS[report.fair_value.reason], report.fair_value.reason.label

    if not report.valuation.close_is_fresh:
        return EliminationReason.PRICE_STALE, report.valuation.price_text

    undervaluation = report.fair_value.base.undervaluation

    if undervaluation < criteria.min_undervaluation:
        return EliminationReason.BELOW_MIN_UNDERVALUATION, f"低估幅度 {undervaluation:.1%} 未達 {criteria.min_undervaluation:.1%}"

    return None, ""


def _by_undervaluation(reports: list[ValuationReport]) -> tuple[ValuationReport, ...]:
    return tuple(sorted(reports, key=lambda report: (-(report.undervaluation or 0.0), report.stock.stock_id)))


@dataclass(frozen=True)
class ScanCriteria:
    target_pe: TargetPe
    min_undervaluation: float
    """A ratio: 0.3 keeps stocks priced at least 30% below the base fair price."""

    def __post_init__(self) -> None:
        if not math.isfinite(self.min_undervaluation) or self.min_undervaluation < 0:
            raise ValueError("最低低估幅度必須是大於或等於 0 的有限數字")


class ScanStep(StrEnum):
    VALUATION = auto()
    TECHNICAL = auto()

    @property
    def label(self) -> str:
        return "估值" if self == ScanStep.VALUATION else "技術面"


class EliminationReason(StrEnum):
    EPS_UNAVAILABLE = auto()
    EPS_NOT_POSITIVE = auto()
    PRICE_MISSING = auto()
    PRICE_STALE = auto()
    BELOW_MIN_UNDERVALUATION = auto()
    NO_PRICE_HISTORY = auto()
    TECHNICAL_HARD_FAILURE = auto()

    @property
    def step(self) -> ScanStep:
        if self in (EliminationReason.NO_PRICE_HISTORY, EliminationReason.TECHNICAL_HARD_FAILURE):
            return ScanStep.TECHNICAL

        return ScanStep.VALUATION

    @property
    def label(self) -> str:
        return ELIMINATION_LABELS[self]


ELIMINATION_LABELS = {
    EliminationReason.EPS_UNAVAILABLE: "EPS 資料不足",
    EliminationReason.EPS_NOT_POSITIVE: "EPS ≤ 0",
    EliminationReason.PRICE_MISSING: "無有效股價",
    EliminationReason.PRICE_STALE: "股價過期",
    EliminationReason.BELOW_MIN_UNDERVALUATION: "低估幅度未達條件",
    EliminationReason.NO_PRICE_HISTORY: "無可用日線資料（缺漏或已過期），無法執行技術策略",
    EliminationReason.TECHNICAL_HARD_FAILURE: "技術面 hard failure",
}

VALUATION_REASONS = {
    PeNotApplicableReason.EPS_UNAVAILABLE: EliminationReason.EPS_UNAVAILABLE,
    PeNotApplicableReason.EPS_ZERO: EliminationReason.EPS_NOT_POSITIVE,
    PeNotApplicableReason.EPS_NEGATIVE: EliminationReason.EPS_NOT_POSITIVE,
    PeNotApplicableReason.INVALID_PRICE: EliminationReason.PRICE_MISSING,
}


@dataclass(frozen=True)
class ScanElimination:
    report: ValuationReport
    reason: EliminationReason
    detail: str


@dataclass(frozen=True)
class ValuationScan:
    """
    The US-108 and US-109 funnel. Survivors passed every step run so far, sorted by undervaluation.

    It carries no action or signal: a low P/E never becomes a BUY here.
    """

    criteria: ScanCriteria
    survivors: tuple[ValuationReport, ...]
    eliminations: tuple[ScanElimination, ...]
    technical_strategy_id: str | None = None

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
    def valuation_survivors(self) -> tuple[ValuationReport, ...]:
        """Stocks that passed the valuation step, whatever happened at the technical step."""
        technical = [elimination.report for elimination in self.technical_eliminations.values()]

        return _by_undervaluation([*self.survivors, *technical])

    @property
    def technical_eliminations(self) -> dict[str, ScanElimination]:
        return {
            elimination.report.stock.stock_id: elimination
            for elimination in self.eliminations
            if elimination.reason.step == ScanStep.TECHNICAL
        }

    def elimination_counts(self, step: ScanStep) -> Counter[EliminationReason]:
        return Counter(elimination.reason for elimination in self.eliminations if elimination.reason.step == step)
