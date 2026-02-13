"""
Use Case: Collect and filter articles for sentiment analysis.

Runs AFTER technical filtering to avoid wasting API calls.
"""
from backend.src.a_domain.model.market.stock import Stock
from backend.src.a_domain.ports.market.news_repository import INewsRepository
from backend.src.a_domain.ports.system.logging_provider import ILoggingProvider
from backend.src.a_domain.rules.collect.quality_rule import QualityRule
from backend.src.b_application.schemas.config import AppConfig


class NewsFeed:
    """
    Fetches and filters textual data for sentiment analysis.
    Only runs on stocks that passed technical screening.
    """

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

    async def execute(self, candidates: list[Stock]) -> list[Stock]:
        if not candidates:
            return []

        self._logger.info(f"Collecting articles for {len(candidates)} survivors...")

        for candidate in candidates:
            try:
                raw_articles = await self._article_repo.get_by_stock_id(
                    stock_id=candidate.stock_id,
                    limit=self._config.article_fetch_limit,
                )

                if not raw_articles:
                    self._logger.debug(f"No articles found for {candidate.stock_id}")
                    candidate.articles = []
                    continue

                high_quality = [a for a in raw_articles if self._quality_filter.is_high_quality(a)]
                candidate.articles = high_quality

                self._logger.trace(
                    f"{candidate.stock_id}: {len(raw_articles)} fetched -> {len(high_quality)} kept"
                )

            except Exception as e:
                self._logger.error(f"Failed to collect articles for {candidate.stock_id}: {e}")
                candidate.articles = []

        self._logger.info("Article collection complete")
        return candidates
