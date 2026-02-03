"""
Technical Screening Policy.

This is the master policy that orchestrates all trading rules.

The policy supports three rule categories:
1. Setup Rules: "Is this stock in a good technical setup?" (trend, momentum)
2. Safety Rules: "Is it safe to enter?" (not overbought, has liquidity)
3. Entry Timing Rules: "Is NOW the right moment?" (intraday only)

Reference Architecture:
- Elder, A. (1993). Triple Screen Trading System.
  Screen 1: Weekly trend (we use daily)
  Screen 2: Daily oscillators for timing
  Screen 3: Intraday for precise entry
"""
from backend.src.a_domain.model.analysis.analysis_context import AnalysisContext
from backend.src.a_domain.rules.base import TradingRule
from backend.src.a_domain.types.enums import CandidateSource


class TechnicalScreeningPolicy:
    """
    Master Policy: Evaluates all technical rules.
    
    Rule Application Matrix:
    ┌─────────────────────┬────────────────┬──────────────┬───────────────┐
    │ Source              │ Setup Rules    │ Safety Rules │ Entry Timing  │
    ├─────────────────────┼────────────────┼──────────────┼───────────────┤
    │ TECHNICAL_WATCHLIST │ ✅ All         │ ✅ All       │ ✅ If intraday│
    │ SOCIAL_BUZZ         │ ❌ Skip        │ ✅ All       │ ✅ If intraday│
    │ MANUAL_INPUT        │ ❌ Skip        │ ✅ All       │ ✅ If intraday│
    └─────────────────────┴────────────────┴──────────────┴───────────────┘
    
    Rationale:
    - Technical watchlist stocks: Need full validation (trend + momentum + safety + timing)
    - Buzz stocks: Already have trend (social proof), only need safety + timing
    - Manual input: User knows something, only apply safety + timing
    """

    def __init__(
        self,
        setup_rules: list[TradingRule],
        safety_rules: list[TradingRule],
        entry_timing_rules: list[TradingRule] | None = None,
    ):
        """
        Args:
            setup_rules: Full technical validation rules (trend, momentum)
            safety_rules: Risk management rules (liquidity, not overbought)
            entry_timing_rules: Intraday-specific rules
        """
        self._setup_rules = setup_rules
        self._safety_rules = safety_rules
        self._entry_timing_rules = entry_timing_rules or []

    def evaluate(
        self,
        context: AnalysisContext,
        is_intraday: bool = True,
    ) -> list[str]:
        """
        Evaluate rules and return names of FAILED rules.
        
        Args:
            context: Analysis context with stock data and indicators
            is_intraday: If True, applies entry timing rules
            
        Returns:
            List of failed rule names. Empty = all passed.
        """
        failed_rules: list[str] = []

        # 1. Apply setup rules based on source
        if context.source == CandidateSource.TECHNICAL_WATCHLIST:
            # Cold data: Need full technical validation
            for rule in self._setup_rules:
                if not rule.is_satisfied(context):
                    failed_rules.append(rule.name)

        # 2. Apply safety rules (always)
        for rule in self._safety_rules:
            if not rule.is_satisfied(context):
                failed_rules.append(rule.name)

        # 3. Apply entry timing rules (only if intraday)
        if is_intraday:
            for rule in self._entry_timing_rules:
                if not rule.is_satisfied(context):
                    failed_rules.append(rule.name)

        return failed_rules

    def get_rule_summary(self) -> dict[str, list[str]]:
        """Returns summary of all configured rules."""
        return {
            "setup_rules": [r.name for r in self._setup_rules],
            "safety_rules": [r.name for r in self._safety_rules],
            "entry_timing_rules": [r.name for r in self._entry_timing_rules],
        }


