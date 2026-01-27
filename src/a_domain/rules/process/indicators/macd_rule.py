from typing import TYPE_CHECKING

from src.a_domain.rules.base import TradingRule

if TYPE_CHECKING:
    from src.a_domain.model.analysis.analysis_context import AnalysisContext


class BullishMacdCrossoverRule(TradingRule):
    """
    Rule: MACD Line must be greater than Signal Line.
    """

    @property
    def name(self) -> str:
        return "MACD Bullish Crossover"

    def is_satisfied(self, context: "AnalysisContext") -> bool:
        if context.macd is None or context.macd.line is None or context.macd.signal is None:
            return False
        return context.macd.line > context.macd.signal
