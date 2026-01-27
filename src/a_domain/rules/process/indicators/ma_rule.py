from typing import TYPE_CHECKING

from src.a_domain.rules.base import TradingRule

if TYPE_CHECKING:
    from src.a_domain.model.analysis.analysis_context import AnalysisContext


class PriceAboveMovingAverageRule(TradingRule):
    """
    Rule: Price must be above the 20-period Moving Average (Bullish Trend).
    """

    @property
    def name(self) -> str:
        return "Price > MA20"

    def is_satisfied(self, context: "AnalysisContext") -> bool:
        if context.ma is None or context.ma.ma_20 is None or context.current_price is None:
            return False
        return context.current_price > context.ma.ma_20
