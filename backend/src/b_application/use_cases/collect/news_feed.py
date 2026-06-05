from icontract import require

from a_domain.ports.market.news_provider import INewsProvider
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.rules.collect import ArticleQualityRule
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
        config: AppConfig,
        logger: ILoggingProvider,
    ):
        self._news_provider = news_provider
        self._config = config
        self._quality = ArticleQualityRule(
            spam_keywords=frozenset(config.collect_rules.spam_keywords),
            financial_keywords=frozenset(config.collect_rules.financial_keywords),
            min_chars_stock=config.quality.min_chars_stock,
            min_chars_news=config.quality.min_chars_news,
            min_chars_gossip=config.quality.min_chars_gossip,
        )
        self._logger = logger

    @require(lambda context: len(context.survivors) > 0, "Pipeline guarantees survivors exist")
    async def execute(self, context: PipelineContext) -> None:
        stocks = context.survivors

        self._logger.info(f"Collecting articles for {len(stocks)} survivors.")

        for stock in stocks:
            try:
                raw_articles = await self._news_provider.fetch_news(
                    stock_id=stock.stock_id,
                    limit=self._config.analysis.article_fetch_limit,
                )

                if not raw_articles:
                    stock.articles = []
                    continue

                self._news_provider.save_as_md_file(stock.stock_id, raw_articles)
                stock.articles = [article for article in raw_articles if self._quality.is_high_quality(article)]

            except Exception as e:
                self._logger.error(f"Failed to collect articles for {stock.stock_id}: {e}")
                stock.articles = []

        self._logger.info("Article collection complete")
