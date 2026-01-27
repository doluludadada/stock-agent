from typing import TYPE_CHECKING

from src.a_domain.rules.base import TradingRule

if TYPE_CHECKING:
    from src.a_domain.model.analysis.analysis_context import AnalysisContext


class RsiHealthyRule(TradingRule):
    """
    Rule: RSI should be strong (>50) but not extremely overheated (<85).
    """

    @property
    def name(self) -> str:
        return "RSI Healthy (50-85)"

    def is_satisfied(self, context: "AnalysisContext") -> bool:
        if context.rsi is None or context.rsi.val_14 is None:
            return False
        return 50 < context.rsi.val_14 < 85
