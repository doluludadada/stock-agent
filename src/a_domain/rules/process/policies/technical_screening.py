from src.a_domain.model.analysis.analysis_context import AnalysisContext
from src.a_domain.rules.base import TradingRule
from src.a_domain.types.enums import CandidateSource


class TechnicalScreeningPolicy:
    """
    Domain Policy: Evaluates technical rules based on the candidate's source.

    - TECHNICAL_WATCHLIST: Applies strict entry rules (e.g., Golden Cross, Breakout).
    - SOCIAL_BUZZ / MANUAL: Applies safety/risk rules (e.g., Avoid falling knife, RSI not overheated).
    """

    def __init__(self, standard_rules: list[TradingRule], momentum_safety_rules: list[TradingRule]):
        self._standard_rules = standard_rules
        self._momentum_safety_rules = momentum_safety_rules

    def evaluate(self, context: "AnalysisContext") -> list[str]:
        """
        Returns a list of names of the rules that FAILED.
        If empty, the screening is passed.
        """
        failed_rules: list[str] = []
        rules_to_apply: list[TradingRule] = []

        # Determine which rule set to apply based on the source
        match context.source:
            case CandidateSource.TECHNICAL_WATCHLIST:
                # Strict entry criteria for cold data
                rules_to_apply = self._standard_rules

            case CandidateSource.SOCIAL_BUZZ | CandidateSource.MANUAL_INPUT:
                # Safety checks for hot/manual data (Trend is already assumed, check Risk)
                rules_to_apply = self._momentum_safety_rules

            case _:
                # Default fallback
                rules_to_apply = self._standard_rules

        # Evaluate selected rules
        for rule in rules_to_apply:
            if not rule.is_satisfied(context):
                failed_rules.append(rule.name)

        return failed_rules
