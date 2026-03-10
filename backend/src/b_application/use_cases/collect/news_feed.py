"""
Use Case: Collect and filter articles for sentiment analysis.
Runs AFTER technical filtering to avoid wasting API calls.
"""
from a_domain.model.market.stock import Stock
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.market.news_repository import INewsRepository
from a_domain.rules.collect.quality_rule import QualityRule
from b_application.schemas.config import AppConfig


class NewsFeed:
    """Fetches and filters textual data for sentiment analysis."""

    def __init__(
        self,
        article_repo: INewsRepository,
        quality_filter: QualityRule,
        config: AppConfig,
        logger: ILoggingProvider,
    ):
        self._article_repo = article_repo
        self._quality_filter = quality_filter
        self._config = config
        self._logger = logger

    async def execute(self, stocks: list[Stock]) -> list[Stock]:
        if not stocks:
            return []

        self._logger.info(f"Collecting articles for {len(stocks)} survivors...")

        for stock in stocks:
            try:
                raw_articles = await self._article_repo.get_by_stock_id(
                    stock_id=stock.stock_id, limit=self._config.article_fetch_limit,
                )
                if not raw_articles:
                    stock.articles = []
                    continue

                stock.articles = [a for a in raw_articles if self._quality_filter.is_high_quality(a)]
            except Exception as e:
                self._logger.error(f"Failed to collect articles for {stock.stock_id}: {e}")
                stock.articles = []

        self._logger.info("Article collection complete")
        return stocks
