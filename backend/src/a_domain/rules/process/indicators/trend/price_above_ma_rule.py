from a_domain.model.market.stock import Stock
from a_domain.rules.base import TradingRule
from a_domain.rules.process.indicators.utils import get_ma_value
from a_domain.types.enums import MaPeriod


class PriceAboveMaRule(TradingRule):
    """Price must be above the specified Moving Average."""

    def __init__(self, ma_period: MaPeriod):
        self._ma_period = ma_period

    @property
    def name(self) -> str:
        return f"Price Above {self._ma_period.value}"

    def apply(self, stock: Stock) -> bool:
        if stock.indicators is None or stock.indicators.ma is None:
            return False
        ma_value = get_ma_value(stock.indicators.ma, self._ma_period)
        if ma_value is None or stock.current_price is None:
            return False
        return stock.current_price > ma_value
