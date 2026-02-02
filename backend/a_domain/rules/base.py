"""
Base Trading Rule Interface.

All trading rules must implement this interface.
"""
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from src.a_domain.model.analysis.analysis_context import AnalysisContext


class TradingRule(Protocol):
    """
    Interface for a single, atomic trading rule.
    
    Each rule answers ONE specific question:
    - "Is the trend bullish?" (Trend rule)
    - "Is momentum strong?" (Momentum rule)
    - "Is volume confirming?" (Volume rule)
    
    Rules should be:
    1. Simple - One condition only
    2. Testable - Easy to unit test
    3. Configurable - Thresholds via constructor
    4. Documented - Reference to source material
    """

    @property
    def name(self) -> str:
        """
        Human-readable name for logging and debugging.
        Example: "RSI Healthy (50-70)"
        """
        ...

    def is_satisfied(self, context: "AnalysisContext") -> bool:
        """
        Evaluate the rule against the analysis context.
        
        Returns:
            True if the rule passes (bullish signal)
            False if the rule fails (avoid entry)
        """
        ...
