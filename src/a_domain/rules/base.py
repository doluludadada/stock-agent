from decimal import Decimal
from typing import Protocol

from src.a_domain.model.analysis.technical_indicators import TechnicalIndicators


class TradingRule(Protocol):
    """
    Interface for a single, atomic trading rule.
    """

    @property
    def name(self) -> str:
        """Name of the rule for logging/reasoning."""
        ...

    def is_satisfied(
        self, indicators: TechnicalIndicators, current_price: Decimal
    ) -> bool:
        """
        Evaluates the rule against the provided technical context.
        """
        ...
