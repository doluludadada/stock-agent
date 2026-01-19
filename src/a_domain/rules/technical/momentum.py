from decimal import Decimal
from src.a_domain.rules.base import TradingRule
from src.a_domain.model.analysis.technical_indicators import TechnicalIndicators


class RsiHealthyRule(TradingRule):
    """
    Rule: RSI should be strong (>50) but not extremely overheated (<85).
    """

    @property
    def name(self) -> str:
        return "RSI Healthy (50-85)"

    def is_satisfied(
        self, indicators: TechnicalIndicators, current_price: Decimal
    ) -> bool:
        if indicators.rsi_14 is None:
            return False
        return 50 < indicators.rsi_14 < 85
