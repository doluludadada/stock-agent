from backend.src.a_domain.model.market.stock import Stock
from backend.src.a_domain.rules.base import TradingRule


class GapRule(TradingRule):
    """Stock should not have gapped up excessively."""

    def __init__(self, max_gap_pct: float = 0.03):
        self._max_gap = max_gap_pct

    @property
    def name(self) -> str:
        return "Gap Check"

    def apply(self, stock: Stock) -> bool:
        if stock.today is None or stock.yesterday is None:
            return True
        if stock.yesterday.close == 0:
            return True
        gap = float(
            (stock.today.open - stock.yesterday.close) / stock.yesterday.close
        )
        return gap < self._max_gap
