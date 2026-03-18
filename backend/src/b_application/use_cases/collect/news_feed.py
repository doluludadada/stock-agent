from a_domain.ports.market.news_provider import INewsProvider
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.rules.collect.quality_rule import QualityRule
from b_application.schemas.config import AppConfig
from b_application.schemas.pipeline_context import PipelineContext


class NewsFeed:
    """
    Use Case: Collect and filter articles for sentiment analysis.
    Runs AFTER technical filtering to avoid wasting API calls.
    """

    def __init__(
        self,
        news_provider: INewsProvider,
        quality_filter: QualityRule,
        config: AppConfig,
        logger: ILoggingProvider,
    ):
        self._news = news_provider
        self._quality = quality_filter
        self._config = config
        self._logger = logger

    async def execute(self, workflow_state: PipelineContext) -> None:
        stocks = workflow_state.survivors
        if not stocks:
            return

        self._logger.info(f"Collecting articles for {len(stocks)} survivors...")

        for stock in stocks:
            try:
                raw_articles = await self._news.fetch_news(
                    stock_id=stock.stock_id,
                    limit=self._config.analysis.article_fetch_limit,
                )
                if not raw_articles:
                    stock.articles = []
                    continue

                self._news.save_as_md_file(stock.stock_id, raw_articles)
                stock.articles = [a for a in raw_articles if self._quality.is_high_quality(a)]
            except Exception as e:
                self._logger.error(f"Failed to collect articles for {stock.stock_id}: {e}")
                stock.articles = []

        self._logger.info("Article collection complete")
