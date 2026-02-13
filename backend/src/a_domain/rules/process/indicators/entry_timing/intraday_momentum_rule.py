from typing import TYPE_CHECKING

from backend.src.a_domain.rules.base import TradingRule

if TYPE_CHECKING:
    from backend.src.a_domain.model.market.stock import Stock


class IntradayMomentumRule(TradingRule):
    """Current price should be above today's open."""

    @property
    def name(self) -> str:
        return "Intraday Momentum"

    def is_satisfied(self, candidate: "Stock") -> bool:
        if candidate.current_price is None or candidate.today_open is None:
            return False
        if candidate.today_open <= 0:
            return False
        return candidate.current_price > candidate.today_open
