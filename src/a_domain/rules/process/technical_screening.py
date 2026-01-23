from decimal import Decimal

from src.a_domain.model.analysis.screening_result import ScreeningResult
from src.a_domain.model.analysis.technical_indicators import TechnicalIndicators
from src.a_domain.rules.base import TradingRule


class TechnicalScreeningPolicy:
    """
    Aggregates multiple TradingRules to form a cohesive screening policy.
    Evaluates all rules and reports which ones failed.
    """

    def __init__(self, rules: list[TradingRule]):
        self._rules = rules

    def evaluate(self, indicators: TechnicalIndicators, current_price: Decimal) -> ScreeningResult:
        failed_rule_names: list[str] = []
        evaluation_details: dict[str, str] = {}

        for rule in self._rules:
            if not rule.is_satisfied(indicators, current_price):
                failed_rule_names.append(rule.name)

        return ScreeningResult(
            passed=len(failed_rule_names) == 0,
            failed_rules=failed_rule_names,
            details=evaluation_details,
        )
