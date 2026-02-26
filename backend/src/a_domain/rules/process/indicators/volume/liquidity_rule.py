from backend.src.a_domain.model.market.stock import Stock
from backend.src.a_domain.rules.base import TradingRule


class LiquidityRule(TradingRule):
    """Stock must have minimum daily trading volume."""

    def __init__(self, min_daily_volume: int = 500):
        self._min_volume = min_daily_volume

    @property
    def name(self) -> str:
        return "Liquidity Check"

    def apply(self, stock: Stock) -> bool:
        if not stock.ohlcv:
            return False
        recent_volumes = [bar.volume for bar in stock.ohlcv[-5:]]
        if not recent_volumes:
            return False
        avg_volume = sum(recent_volumes) / len(recent_volumes)
        return avg_volume >= self._min_volume
