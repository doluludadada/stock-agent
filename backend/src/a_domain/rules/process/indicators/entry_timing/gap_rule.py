from typing import TYPE_CHECKING

from backend.src.a_domain.rules.base import TradingRule

if TYPE_CHECKING:
    from backend.src.a_domain.model.market.stock import Stock


class GapRule(TradingRule):
    """Stock should not have gapped up excessively."""

    def __init__(self, max_gap_pct: float = 0.03):
        self._max_gap = max_gap_pct

    @property
    def name(self) -> str:
        return "Gap Check"

    def is_satisfied(self, candidate: "Stock") -> bool:
        if candidate.gap_pct is None:
            return True
        return candidate.gap_pct < self._max_gap
