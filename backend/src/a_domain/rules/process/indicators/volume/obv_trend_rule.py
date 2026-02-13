from typing import TYPE_CHECKING

from backend.src.a_domain.rules.base import TradingRule

if TYPE_CHECKING:
    from backend.src.a_domain.model.market.stock import Stock


class ObvTrendRule(TradingRule):
    """On-Balance Volume (OBV) should be above its 20-day MA (rising trend)."""

    @property
    def name(self) -> str:
        return "OBV Trend"

    def is_satisfied(self, candidate: "Stock") -> bool:
        if candidate.indicators is None or candidate.indicators.obv is None:
            return True
        obv = candidate.indicators.obv
        if obv.obv is None or obv.obv_ma_20 is None:
            return True
        return obv.obv > obv.obv_ma_20
