from collections.abc import Mapping

from a_domain.model.market.stock import Stock
from a_domain.model.system.stats import SystemStats
from a_domain.ports.market.social_media_provider import ISocialMediaProvider
from a_domain.ports.market.stock_provider import IStockProvider
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.rules.collect import SocialBuzzCriteria
from b_application.config.app_config import AppConfig


class BuzzScanner:
    """
    Loads social-buzz stocks and attaches their buzz articles. A stock this run already loaded is reused.
    """

    def __init__(
        self, social_media_provider: ISocialMediaProvider, stock_provider: IStockProvider, logger: ILoggingProvider, config: AppConfig
    ) -> None:
        rules = config.collect_rules
        self._social_media_provider = social_media_provider
        self._stock_provider = stock_provider
        self._logger = logger
        self._article_limit = rules.social_article_limit
        self._criteria = SocialBuzzCriteria(min_mentions=rules.buzz_min_mentions, min_engagement=rules.buzz_min_engagement)

    async def execute(self, known: Mapping[str, Stock], stats: SystemStats) -> list[Stock]:
        self._logger.info("Scanning social media for buzz...")
        articles = await self._social_media_provider.fetch_social_articles(limit=self._article_limit)

        if not articles:
            self._logger.info("No buzz articles found.")
            return []

        self._social_media_provider.save_social_media_data(articles)
        buzz_stocks: list[Stock] = []

        for stock_id, stock_articles in self._criteria.apply(articles).items():
            stock = known.get(stock_id) or await self._stock_provider.get_by_id(stock_id)

            if stock is None:
                self._logger.warning(f"Buzz stock not found: {stock_id}")
                continue

            stock.articles.extend(stock_articles)
            buzz_stocks.append(stock)

        stats.buzz_scanned = len({article.stock_id for article in articles})
        stats.buzz_qualified = len(buzz_stocks)
        stats.total_scanned = len(buzz_stocks)
        self._logger.info(f"Buzz candidates: {stats.buzz_scanned} -> {stats.buzz_qualified}")

        return buzz_stocks
