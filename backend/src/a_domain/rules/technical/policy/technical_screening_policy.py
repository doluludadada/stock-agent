from dataclasses import dataclass, field

from a_domain.model.market.stock import Stock
from a_domain.rules.technical.criteria.base import TechnicalCriterion
from a_domain.types.enums import CandidateSource


@dataclass(frozen=True)
class TechnicalScreeningPolicy:
    """
    Applies technical criteria to a stock.

    Policy owns the grouping:
        - setup_must_pass
        - safety_must_pass
        - should_pass
        - info_only
        - entry_timing_must_pass

    Criteria own only the condition.
    """

    setup_must_pass: list[TechnicalCriterion]
    safety_must_pass: list[TechnicalCriterion]
    should_pass: list[TechnicalCriterion]
    info_only: list[TechnicalCriterion]
    entry_timing_must_pass: list[TechnicalCriterion] = field(default_factory=list)

    def evaluate(self, stock: Stock) -> None:
        stock.hard_failures.clear()
        stock.soft_failures.clear()
        stock.observations.clear()

        is_manual = stock.source == CandidateSource.MANUAL_INPUT

        if stock.source == CandidateSource.TECHNICAL_WATCHLIST:
            self._apply_hard(stock, self.setup_must_pass)

        self._apply_safety(stock, self.safety_must_pass, is_manual)
        self._apply_timing(stock, self.entry_timing_must_pass, is_manual)
        self._apply_soft(stock, self.should_pass)
        self._apply_info(stock, self.info_only)

    def evaluate_entry_timing(self, stock: Stock) -> bool:
        for criterion in self.entry_timing_must_pass:
            if criterion.apply(stock):
                continue

            stock.hard_failures.append(criterion.name)
            return False

        return True

    def _apply_hard(self, stock: Stock, criteria: list[TechnicalCriterion]) -> None:
        for criterion in criteria:
            if not criterion.apply(stock):
                stock.hard_failures.append(criterion.name)

    def _apply_safety(
        self,
        stock: Stock,
        criteria: list[TechnicalCriterion],
        is_manual: bool,
    ) -> None:
        for criterion in criteria:
            if criterion.apply(stock):
                continue

            if is_manual:
                stock.soft_failures.append(f"Safety: {criterion.name}")
            else:
                stock.hard_failures.append(criterion.name)

    def _apply_timing(
        self,
        stock: Stock,
        criteria: list[TechnicalCriterion],
        is_manual: bool,
    ) -> None:
        for criterion in criteria:
            if criterion.apply(stock):
                continue

            if is_manual:
                stock.soft_failures.append(f"Timing: {criterion.name}")
            else:
                stock.hard_failures.append(criterion.name)

    def _apply_soft(self, stock: Stock, criteria: list[TechnicalCriterion]) -> None:
        for criterion in criteria:
            if not criterion.apply(stock):
                stock.soft_failures.append(criterion.name)

    def _apply_info(self, stock: Stock, criteria: list[TechnicalCriterion]) -> None:
        for criterion in criteria:
            if not criterion.apply(stock):
                stock.observations.append(criterion.name)
