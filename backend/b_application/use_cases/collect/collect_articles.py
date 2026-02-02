"""
Use Case: Collect and filter articles for sentiment analysis.

This runs AFTER technical filtering to avoid wasting API calls
on stocks that won't pass anyway.
"""
from src.a_domain.model.analysis.analysis_context import AnalysisContext
from src.a_domain.ports.analysis.quality_filter_provider import IQualityFilterProvider
from src.a_domain.ports.market.article_repository import IArticleRepository
from src.a_domain.ports.system.logging_provider import ILoggingProvider
from src.b_application.schemas.config import AppConfig


class CollectArticles:
    """
    Fetches and filters textual data for sentiment analysis.
    
    Only runs on stocks that passed technical screening (resource optimization).
    """

    def __init__(
        self,
        article_repo: IArticleRepository,
        quality_filter: IQualityFilterProvider,
        config: AppConfig,
        logger: ILoggingProvider,
    ):
        self._article_repo = article_repo
        self._quality_filter = quality_filter
        self._config = config
        self._logger = logger

    async def execute(self, contexts: list[AnalysisContext]) -> list[AnalysisContext]:
        if not contexts:
            return []

        self._logger.info(f"Collecting articles for {len(contexts)} survivors...")

        for ctx in contexts:
            try:
                # Fetch raw articles
                raw_articles = await self._article_repo.get_by_stock_id(
                    stock_id=ctx.stock.stock_id,
                    limit=self._config.article_fetch_limit,
                )

                if not raw_articles:
                    self._logger.debug(f"No articles found for {ctx.stock.stock_id}")
                    ctx.articles = []
                    continue

                # Apply quality filter
                high_quality = [a for a in raw_articles if self._quality_filter.is_high_quality(a)]

                ctx.articles = high_quality
                self._logger.trace(
                    f"{ctx.stock.stock_id}: {len(raw_articles)} fetched -> {len(high_quality)} kept"
                )

            except Exception as e:
                self._logger.error(f"Failed to collect articles for {ctx.stock.stock_id}: {e}")
                ctx.articles = []

        self._logger.success("Article collection complete")
        return contexts
