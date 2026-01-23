from decimal import Decimal

from src.a_domain.model.analysis.technical_indicators import TechnicalIndicators
from src.a_domain.rules.base import TradingRule


class PriceAboveMovingAverageRule(TradingRule):
    """
    Rule: Price must be above the 20-period Moving Average (Bullish Trend).
    """

    @property
    def name(self) -> str:
        return "Price > MA20"

    def is_satisfied(self, indicators: TechnicalIndicators, current_price: Decimal) -> bool:
        if indicators.ma_20 is None:
            return False
        return current_price > indicators.ma_20
