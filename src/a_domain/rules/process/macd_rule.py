from decimal import Decimal

from src.a_domain.model.analysis.technical_indicators import TechnicalIndicators
from src.a_domain.rules.base import TradingRule


class BullishMacdCrossoverRule(TradingRule):
    """
    Rule: MACD Line must be greater than Signal Line.
    """

    @property
    def name(self) -> str:
        return "MACD Bullish Crossover"

    def is_satisfied(self, indicators: TechnicalIndicators, current_price: Decimal) -> bool:
        if indicators.macd_line is None or indicators.macd_signal is None:
            return False
        return indicators.macd_line > indicators.macd_signal
