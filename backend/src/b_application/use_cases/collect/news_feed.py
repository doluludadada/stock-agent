from a_domain.model.market.stock import Stock
from a_domain.ports.market.news_provider import INewsProvider
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.rules.collect import ArticleQualityRule
from b_application.schemas.config import AppConfig
from b_application.schemas.pipeline_status import PipelineStatus


class NewsFeed:
    """
    Collects accepted news articles for stocks.
    """

    def __init__(
        self,
        news_provider: INewsProvider,
        config: AppConfig,
        logger: ILoggingProvider,
    ) -> None:
        self._news_provider = news_provider
        self._quality = ArticleQualityRule(
            spam_keywords=frozenset(config.collect_rules.spam_keywords),
            financial_keywords=frozenset(config.collect_rules.financial_keywords),
            min_chars_stock=config.quality.min_chars_stock,
            min_chars_news=config.quality.min_chars_news,
            min_chars_gossip=config.quality.min_chars_gossip,
        )
        self._article_fetch_limit = config.analysis.article_fetch_limit
        self._logger = logger

    async def execute(
        self,
        stocks: list[Stock],
        status: PipelineStatus,
    ) -> None:
        self._logger.info(f"Collecting news for {len(stocks)} stocks.")

        for stock in stocks:
            try:
                news = await self._news_provider.fetch_news(
                    stock_id=stock.stock_id,
                    limit=self._article_fetch_limit,
                )

                accepted_news = [article for article in news if self._quality.is_high_quality(article)]

                stock.articles.extend(accepted_news)

                if accepted_news:
                    self._news_provider.save_as_md_file(
                        stock.stock_id,
                        accepted_news,
                    )
                    
            except Exception as error:
                message = f"Failed to collect news for {stock.stock_id}: {error}"
                self._logger.error(message)
                status.stats.add_error(message)

        self._logger.info("News collection complete.")
