from src.a_domain.model.analysis.analysis_context import AnalysisContext
from src.a_domain.ports.analysis.quality_filter_provider import IQualityFilterProvider
from src.a_domain.ports.market.article_repository import IArticleRepository
from src.a_domain.ports.system.logging_provider import ILoggingProvider
from src.b_application.schemas.config import AppConfig


class ArticleCollector:
    """
    Use Case: Fetches and filters textual data for Sentiment Analysis.

    This should typically run ONLY on stocks that have passed the
    Technical Filter to act as a resource-saving funnel.
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
        """
        Enriches the provided contexts with filtered articles.
        Returns the modified list of contexts.
        """
        if not contexts:
            return []

        self._logger.info(f"Collecting articles for {len(contexts)} qualified stocks...")

        updated_count = 0

        for ctx in contexts:
            try:
                # 1. Fetch Raw Articles
                # The repository handles the source logic (News vs PTT vs Web Search)
                raw_articles = await self._article_repo.get_by_stock_id(
                    stock_id=ctx.stock.stock_id, limit=self._config.article_fetch_limit
                )

                if not raw_articles:
                    self._logger.debug(f"No articles found for {ctx.stock.stock_id}")
                    continue

                # 2. Apply Quality Filter (Domain Rule)
                # Removes spam, short comments, or irrelevant info
                high_quality_articles = [a for a in raw_articles if self._quality_filter.is_high_quality(a)]

                # 3. Update Context
                ctx.articles = high_quality_articles
                updated_count += 1

                self._logger.trace(
                    f"Stock {ctx.stock.stock_id}: {len(raw_articles)} fetched -> {len(high_quality_articles)} kept."
                )

            except Exception as e:
                self._logger.error(f"Failed to collect articles for {ctx.stock.stock_id}: {e}")
                # We do not drop the context here; we just leave articles empty.
                # The AI Analyzer handles empty articles gracefully (returns neutral score).
                ctx.articles = []

        self._logger.success(f"Article collection complete. enriched {updated_count} stocks.")
        return contexts
