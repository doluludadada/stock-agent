from dataclasses import dataclass, field

from a_domain.model.market.stock import Stock
from a_domain.rules.technical.criteria.base import TechnicalCriterion


@dataclass(frozen=True)
class TechnicalScreeningPolicy:
    """
    TODO:
    This's temperary soluation. Might need to redesinning. 18/Jun/26

    Applies structural technical criteria to a stock.

    Entry timing is intentionally separated from normal evaluation.
    Normal technical screening answers:
        - Is this stock technically acceptable?

    Entry timing answers:
        - Is this exact moment acceptable for a BUY?
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

        self._apply_hard(stock, self.setup_must_pass)
        self._apply_hard(stock, self.safety_must_pass)
        self._apply_soft(stock, self.should_pass)
        self._apply_info(stock, self.info_only)

    def entry_timing_failures(self, stock: Stock) -> list[str]:
        return [criterion.name for criterion in self.entry_timing_must_pass if not criterion.apply(stock)]

    def _apply_hard(self, stock: Stock, criteria: list[TechnicalCriterion]) -> None:
        for criterion in criteria:
            if not criterion.apply(stock):
                stock.hard_failures.append(criterion.name)

    def _apply_soft(self, stock: Stock, criteria: list[TechnicalCriterion]) -> None:
        for criterion in criteria:
            if not criterion.apply(stock):
                stock.soft_failures.append(criterion.name)

    def _apply_info(self, stock: Stock, criteria: list[TechnicalCriterion]) -> None:
        for criterion in criteria:
            if not criterion.apply(stock):
                stock.observations.append(criterion.name)
