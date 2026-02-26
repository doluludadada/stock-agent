"""
Technical Screening Policy.

Orchestrates all trading rules in a three-tier system:
1. must_pass:   Hard gate — failure means elimination
2. should_pass: Soft signal — failure reduces score but doesn't eliminate
3. info_only:   Observation — recorded for audit/debug, no impact on outcome

Reference Architecture:
- Elder, A. (1993). Triple Screen Trading System.
"""
from backend.src.a_domain.model.market.stock import Stock
from backend.src.a_domain.rules.base import TradingRule
from backend.src.a_domain.types.enums import CandidateSource


class TechnicalScreeningPolicy:
    """
    Master Policy: Evaluates all technical rules against a stock.

    Rule Application by Source:
    ┌─────────────────────┬────────────┬─────────────┬────────────┐
    │ Source              │ must_pass  │ should_pass │ info_only  │
    ├─────────────────────┼────────────┼─────────────┼────────────┤
    │ TECHNICAL_WATCHLIST │ ✅ All     │ ✅ All      │ ✅ All     │
    │ SOCIAL_BUZZ         │ ✅ Safety  │ ✅ All      │ ✅ All     │
    │ MANUAL_INPUT        │ ✅ Safety  │ ✅ All      │ ✅ All     │
    └─────────────────────┴────────────┴─────────────┴────────────┘
    """

    def __init__(
        self,
        setup_must_pass: list[TradingRule],
        safety_must_pass: list[TradingRule],
        should_pass: list[TradingRule],
        info_only: list[TradingRule],
        entry_timing_must_pass: list[TradingRule] | None = None,
    ):
        self._setup_must_pass = setup_must_pass
        self._safety_must_pass = safety_must_pass
        self._should_pass = should_pass
        self._info_only = info_only
        self._entry_timing_must_pass = entry_timing_must_pass or []

    def evaluate(self, stock: Stock, is_intraday: bool = True) -> None:
        """
        Evaluate all rules and write results directly to stock.

        Populates:
            stock.hard_failures
            stock.soft_failures
            stock.observations
        """
        stock.hard_failures.clear()
        stock.soft_failures.clear()
        stock.observations.clear()

        # 1. Setup must_pass (only for TECHNICAL_WATCHLIST)
        if stock.source == CandidateSource.TECHNICAL_WATCHLIST:
            for rule in self._setup_must_pass:
                if not rule.apply(stock):
                    stock.hard_failures.append(rule.name)

        # 2. Safety must_pass (always)
        for rule in self._safety_must_pass:
            if not rule.apply(stock):
                stock.hard_failures.append(rule.name)

        # 3. Entry timing must_pass (only intraday)
        if is_intraday:
            for rule in self._entry_timing_must_pass:
                if not rule.apply(stock):
                    stock.hard_failures.append(rule.name)

        # 4. Should-pass (always, soft penalty)
        for rule in self._should_pass:
            if not rule.apply(stock):
                stock.soft_failures.append(rule.name)

        # 5. Info-only (always, observation)
        for rule in self._info_only:
            if not rule.apply(stock):
                stock.observations.append(rule.name)

    def get_rule_summary(self) -> dict[str, list[str]]:
        return {
            "setup_must_pass": [r.name for r in self._setup_must_pass],
            "safety_must_pass": [r.name for r in self._safety_must_pass],
            "entry_timing_must_pass": [r.name for r in self._entry_timing_must_pass],
            "should_pass": [r.name for r in self._should_pass],
            "info_only": [r.name for r in self._info_only],
        }
