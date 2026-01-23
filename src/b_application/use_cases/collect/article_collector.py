from src.a_domain.model.analysis.analysis_context import AnalysisContext
from src.a_domain.model.market.article import Article
from src.a_domain.ports.analysis.quality_filter_port import IQualityFilterPort
from src.a_domain.ports.market.article_repository import IArticleRepository
from src.a_domain.ports.system.logging_port import ILoggingPort
from src.b_application.configuration.schemas import AppConfig


class ArticleCollector:
    """
    Use Case: Fetch and filter articles for each stock.

    Responsibility:
    - Fetch articles from repository for each symbol
    - Apply quality filter to remove noise
    - Populate AnalysisContext with filtered articles
    """

    def __init__(
        self,
        article_repo: IArticleRepository,
        quality_filter: IQualityFilterPort,
        config: AppConfig,
        logger: ILoggingPort,
    ):
        self._article_repo = article_repo
        self._quality_filter = quality_filter
        self._config = config
        self._logger = logger

    async def execute(self, contexts: list[AnalysisContext]) -> list[AnalysisContext]:
        """
        Collect and filter articles for all analysis contexts.

        Args:
            contexts: List of AnalysisContext (already populated with price data).

        Returns:
            Same contexts with articles field populated.
        """
        self._logger.info(f"Collecting articles for {len(contexts)} stocks")

        total_fetched = 0
        total_after_filter = 0

        for ctx in contexts:
            try:
                articles = await self._article_repo.get_by_stock_id(
                    stock_id=ctx.stock.stock_id,
                    limit=self._config.article_fetch_limit,
                )

                total_fetched += len(articles)

                filtered_articles = self._apply_quality_filter(articles)
                total_after_filter += len(filtered_articles)

                ctx.articles = filtered_articles

            except Exception as e:
                self._logger.error(f"Failed to fetch articles for {ctx.stock.stock_id}: {e}")
                ctx.articles = []

        self._logger.success(f"Articles collected: {total_fetched} fetched, {total_after_filter} after filter")
        return contexts

    def _apply_quality_filter(self, articles: list[Article]) -> list[Article]:
        """Filter articles using quality rules (sync transformation)."""
        return [a for a in articles if self._quality_filter.is_high_quality(a)]
