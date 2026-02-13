from typing import TYPE_CHECKING

from backend.src.a_domain.rules.base import TradingRule

if TYPE_CHECKING:
    from backend.src.a_domain.model.market.stock import Stock


class ConsecutiveUpDaysRule(TradingRule):
    """Avoid buying after too many consecutive up days."""

    def __init__(self, max_consecutive_up: int = 4):
        self._max_up = max_consecutive_up

    @property
    def name(self) -> str:
        return "Consecutive Up Days Check"

    def is_satisfied(self, candidate: "Stock") -> bool:
        if not candidate.has_enough_bars(self._max_up + 1):
            return True
        return candidate.consecutive_up_days < self._max_up
