"""
Technical Screening Policy.

Three-tier rule system:
1. must_pass:   Hard gate - failure means elimination
2. should_pass: Soft signal - failure reduces score
3. info_only:   Observation - recorded for audit

Reference: Elder, A. (1993). Triple Screen Trading System.
"""
from a_domain.model.market.stock import Stock
from a_domain.rules.base import TradingRule
from a_domain.types.enums import CandidateSource


class TechnicalScreeningPolicy:
    """
    Rule Application by Source:
    +---------------------+------------+-------------+------------+
    | Source              | must_pass  | should_pass | info_only  |
    +---------------------+------------+-------------+------------+
    | TECHNICAL_WATCHLIST | All        | All         | All        |
    | SOCIAL_BUZZ         | Safety     | All         | All        |
    | MANUAL_INPUT        | Safety     | All         | All        |
    +---------------------+------------+-------------+------------+
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

    def evaluate(self, stock: Stock) -> None:
        stock.hard_failures.clear()
        stock.soft_failures.clear()
        stock.observations.clear()

        # TODO: How about change this setting to dev env?
        is_manual = stock.source == CandidateSource.MANUAL_INPUT

        # 1. Setup must_pass (only for TECHNICAL_WATCHLIST)
        if stock.source == CandidateSource.TECHNICAL_WATCHLIST:
            for rule in self._setup_must_pass:
                if not rule.apply(stock):
                    stock.hard_failures.append(rule.name)

        # 2. Safety must_pass
        for rule in self._safety_must_pass:
            if not rule.apply(stock):
                if is_manual:
                    stock.soft_failures.append(f"Safety: {rule.name}")  # Bypass drop for manual testing
                else:
                    stock.hard_failures.append(rule.name)

        # 3. Entry timing must_pass
        for rule in self._entry_timing_must_pass:
            if not rule.apply(stock):
                if is_manual:
                    stock.soft_failures.append(f"Timing: {rule.name}")  # Bypass drop for manual testing
                else:
                    stock.hard_failures.append(rule.name)

        # 4. Should-pass (soft penalty)
        for rule in self._should_pass:
            if not rule.apply(stock):
                stock.soft_failures.append(rule.name)

        # 5. Info-only (observation)
        for rule in self._info_only:
            if not rule.apply(stock):
                stock.observations.append(rule.name)
