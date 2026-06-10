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

    @require(
        lambda context: len(context.survivors) > 0,
        "News collection requires surviving stocks",
    )
    async def execute(
        self,
        context: PipelineContext,
    ) -> None:
        self._logger.info(f"Collecting news for {len(context.survivors)} stocks.")

        for stock in context.survivors:
            existing_articles = list(stock.articles)

            try:
                fetched_articles = await self._news_provider.fetch_news(
                    stock_id=stock.stock_id,
                    limit=(self._config.analysis.article_fetch_limit),
                )

                if fetched_articles:
                    self._news_provider.save_as_md_file(
                        stock.stock_id,
                        fetched_articles,
                    )

                accepted_articles = [article for article in fetched_articles if self._quality.is_high_quality(article)]

                articles_by_id = {article.id: article for article in existing_articles}

                for article in accepted_articles:
                    articles_by_id[article.id] = article

                stock.articles = list(articles_by_id.values())

            except Exception as error:
                self._logger.error(f"Failed to collect news for {stock.stock_id}: {error}")
                stock.articles = existing_articles

        self._logger.info("News collection complete.")
