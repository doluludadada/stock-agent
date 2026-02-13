from backend.src.a_domain.model.market.stock import Stock
from backend.src.a_domain.rules.base import TradingRule


class HasPriceDataRule(TradingRule):
    """Ensures the stock has OHLCV data to process."""

    @property
    def name(self) -> str:
        return "Data Existence Check"

    def is_satisfied(self, candidate: Stock) -> bool:
        return bool(candidate.ohlcv_data)


class HasArticlesRule(TradingRule):
    """Ensures the stock has news/articles for AI analysis."""

    @property
    def name(self) -> str:
        return "Article Existence Check"

    def is_satisfied(self, candidate: Stock) -> bool:
        return bool(candidate.articles)
