from a_domain.model.market.stock import Stock
from a_domain.rules.base import TradingRule


class ObvTrendRule(TradingRule):
    @property
    def name(self) -> str:
        return "OBV Trend"

    def apply(self, stock: Stock) -> bool:
        if stock.indicators is None or stock.indicators.obv is None:
            return True
        obv = stock.indicators.obv
        if obv.obv is None or obv.obv_ma_20 is None:
            return True
        return obv.obv > obv.obv_ma_20
