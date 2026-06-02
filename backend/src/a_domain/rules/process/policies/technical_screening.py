from dataclasses import dataclass, field

from a_domain.model.market.stock import Stock
from a_domain.rules.base import TradingRule
from a_domain.types.enums import CandidateSource


@dataclass(frozen=True)
class TechnicalScreeningPolicy:
    """
    Technical Screening Policy.

    Applies a three-tier rule verification system (must_pass, should_pass, info_only)
    to filter and categorize incoming stock candidates based on their source (Elder, 1993).
    """

    setup_must_pass: list[TradingRule]
    """
    Setup constraints required only for Technical Watchlist.    
    """
    safety_must_pass: list[TradingRule]
    """
    Core risk gates mandatory for all non-manual inputs.   
    """
    should_pass: list[TradingRule]
    """
    Soft indicators whose failures apply a penalty score.  
    """
    info_only: list[TradingRule]
    """
    Observations recorded strictly for pipeline audits.   
    """
    entry_timing_must_pass: list[TradingRule] = field(default_factory=list)
    """
    Intraday timing filters evaluated before execution.
    """

    def evaluate(self, stock: Stock) -> None:
        """
        Evaluates the stock through the active three-tier policy.

        Mutates the stock's failure and observation lists directly to populate
        the pipeline context metrics.
        """
        stock.hard_failures.clear()
        stock.soft_failures.clear()
        stock.observations.clear()

        is_manual = stock.source == CandidateSource.MANUAL_INPUT

        # 1. Setup must_pass (Strictly for TECHNICAL_WATCHLIST)
        if stock.source == CandidateSource.TECHNICAL_WATCHLIST:
            for rule in self.setup_must_pass:
                if not rule.apply(stock):
                    stock.hard_failures.append(rule.name)

        # 2. Safety must_pass
        for rule in self.safety_must_pass:
            if not rule.apply(stock):
                if is_manual:
                    stock.soft_failures.append(f"Safety: {rule.name}")  # Bypass drop for manual testing
                else:
                    stock.hard_failures.append(rule.name)

        # 3. Entry timing must_pass
        for rule in self.entry_timing_must_pass:
            if not rule.apply(stock):
                if is_manual:
                    stock.soft_failures.append(f"Timing: {rule.name}")  # Bypass drop for manual testing
                else:
                    stock.hard_failures.append(rule.name)

        # 4. Should-pass (Soft penalties)
        for rule in self.should_pass:
            if not rule.apply(stock):
                stock.soft_failures.append(rule.name)

        # 5. Info-only (Logged observations)
        for rule in self.info_only:
            if not rule.apply(stock):
                stock.observations.append(rule.name)
