# TODO: Not wired yet — planned for collect-phase data validation
from backend.src.a_domain.model.market.stock import Stock
from backend.src.a_domain.rules.base import TradingRule


class HasPriceDataRule(TradingRule):
    """Ensures the stock has OHLCV data to process."""

    @property
    def name(self) -> str:
        return "Data Existence Check"

    def apply(self, stock: Stock) -> bool:
        return bool(stock.ohlcv)


class HasArticlesRule(TradingRule):
    """Ensures the stock has news/articles for AI analysis."""

    @property
    def name(self) -> str:
        return "Article Existence Check"

    def apply(self, stock: Stock) -> bool:
        return bool(stock.articles)
