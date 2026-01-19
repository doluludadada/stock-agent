from decimal import Decimal
from src.a_domain.rules.base import TradingRule
from src.a_domain.model.analysis.technical_indicators import TechnicalIndicators
from src.a_domain.model.analysis.screening_result import (
    ScreeningResult,
)


class TechnicalScreeningPolicy:
    """
    Aggregates multiple TradingRules to form a cohesive Level 1 Strategy.
    """

    def __init__(self, rules: list[TradingRule]):
        self._rules = rules

    def evaluate(
        self, indicators: TechnicalIndicators, current_price: Decimal
    ) -> ScreeningResult:
        failed_reasons = []
        details = {}

        for rule in self._rules:
            if not rule.is_satisfied(indicators, current_price):
                failed_reasons.append(rule.name)
                # In a real implementation, you might ask the rule for the specific value
                # e.g. details[rule.name] = f"Actual: {indicators.rsi_14}"

        return ScreeningResult(
            passed=len(failed_reasons) == 0,
            failed_rules=failed_reasons,
            details=details,
        )
