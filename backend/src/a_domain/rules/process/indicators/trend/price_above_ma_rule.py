from decimal import Decimal

from backend.src.a_domain.model.indicators.technical_indicators import MovingAverages
from backend.src.a_domain.model.market.stock import Stock
from backend.src.a_domain.rules.base import TradingRule
from backend.src.a_domain.types.enums import MaPeriod


class PriceAboveMaRule(TradingRule):
    """Price must be above the specified Moving Average."""

    def __init__(self, ma_period: MaPeriod):
        self._ma_period = ma_period

    @property
    def name(self) -> str:
        return f"Price Above {self._ma_period.value}"

    def _get_ma_value(self, ma: MovingAverages) -> Decimal | None:
        match self._ma_period:
            case MaPeriod.MA_5:
                return ma.ma_5
            case MaPeriod.MA_10:
                return ma.ma_10
            case MaPeriod.MA_20:
                return ma.ma_20
            case MaPeriod.MA_60:
                return ma.ma_60
            case MaPeriod.MA_120:
                return ma.ma_120
            case _:
                return None

    def apply(self, stock: Stock) -> bool:
        if stock.indicators is None or stock.indicators.ma is None:
            return False
        ma_value = self._get_ma_value(stock.indicators.ma)
        if ma_value is None or stock.current_price is None:
            return False
        return stock.current_price > ma_value
