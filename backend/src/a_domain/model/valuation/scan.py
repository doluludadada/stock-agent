import statistics
from collections import Counter
from collections.abc import Mapping
from dataclasses import replace
from datetime import date
from typing import Self

from pydantic import PositiveInt
from pydantic.dataclasses import dataclass

from a_domain.model.market.stock import Stock
from a_domain.model.valuation.valuation import PeMedian, PeRatio, StockValuation, ValuationReport
from a_domain.types.enums import EliminationReason, ScanStep
from a_domain.types.values import NonNegativeFiniteFloat, PositiveFiniteFloat


@dataclass(frozen=True)
class MarketValuation:
    """Every listed and OTC stock's valuation for one run, before any user assumption."""

    valuations: Mapping[str, StockValuation]
    last_closed_session: date
    source_warnings: tuple[str, ...] = ()

    def find(self, stock_id: str) -> StockValuation | None:
        return self.valuations.get(stock_id)

    def with_industry_medians(self) -> Self:
        """Each valuation with its industry's median P/E, a reference for the reader, computed once per industry."""
        industries = {valuation.stock.industry for valuation in self.valuations.values() if valuation.stock.industry}
        medians = {industry: self.median_pe(industry) for industry in industries}
        return replace(
            self,
            valuations={
                stock_id: replace(valuation, industry_median_pe=medians.get(valuation.stock.industry or ""))
                for stock_id, valuation in self.valuations.items()
            },
        )

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


@dataclass(frozen=True)
class ScanCriteria:
    target_pe: PositiveFiniteFloat
    min_undervaluation: NonNegativeFiniteFloat
    """A ratio: 0.3 keeps stocks priced at least 30% below the base fair price."""


@dataclass(frozen=True)
class ScanElimination:
    report: ValuationReport
    reason: EliminationReason
    detail: str


@dataclass(frozen=True)
class ValuationScan:
    """
    The undervalued scan's funnel: valuation, then technical. Survivors passed every step run so far, sorted by undervaluation.

    It carries no action or signal: a low P/E never becomes a BUY here.
    """

    criteria: ScanCriteria
    survivors: tuple[ValuationReport, ...]
    eliminations: tuple[ScanElimination, ...]
    max_explanations: PositiveInt
    """How many of the top survivors the scan offers for an AI explanation: each is one AI call."""

    technical_strategy_id: str | None = None

    @staticmethod
    def by_undervaluation(reports: list[ValuationReport]) -> tuple[ValuationReport, ...]:
        """Most undervalued first; ties in stock id order."""
        return tuple(sorted(reports, key=lambda report: (-(report.undervaluation or 0.0), report.stock.stock_id)))

    def after_technical_step(self, strategy_id: str) -> Self:
        """Reads the TechnicalReport the technical filter wrote on each survivor's stock."""
        if self.technical_strategy_id is not None:
            raise ValueError("The technical step runs once")

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
    def survivor_stocks(self) -> list[Stock]:
        """The stock of each survivor, in survivor order: what the technical step screens."""
        return [report.stock for report in self.survivors]

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
