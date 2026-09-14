# backend/src/b_application/use_cases/collect/buzz_scanner.py

from collections import defaultdict

from a_domain.model.market.article import Article
from a_domain.model.market.stock import Stock
from a_domain.ports.market.social_media_provider import ISocialMediaProvider
from a_domain.ports.market.stock_provider import IStockProvider
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.rules.collect import SocialBuzzCriteria
from b_application.schemas.config import AppConfig
from b_application.schemas.pipeline_status import PipelineStatus


class BuzzScanner:
    """
    Loads social-buzz stocks and attaches their buzz articles.
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

    # TODO: I wanna improve this method
    async def execute(self, status: PipelineStatus) -> None:
        self._logger.info("Scanning social media for buzz...")
        articles = await self._social_media_provider.fetch_social_articles(limit=self._article_limit)
        if not articles:
            self._logger.info("No buzz articles found.")
            return

        self._social_media_provider.save_social_media_data(articles)
        articles_by_stock: dict[str, list[Article]] = defaultdict(list)
        for article in articles:
            articles_by_stock[article.stock_id].append(article)

        status.stats.buzz_scanned = len(articles_by_stock)
        buzz_stocks: list[Stock] = []
        for stock_id, stock_articles in articles_by_stock.items():
            engagement = sum(int((article.raw_metadata or {}).get("engagement", 0)) for article in stock_articles)
            if not self._criteria.is_trending(len(stock_articles), engagement):
                continue

            stock = status.stocks_cache.get(stock_id)
            if stock is None:
                stock = await self._stock_provider.get_by_id(stock_id)
            if stock is None:
                self._logger.warning(f"Buzz stock not found: {stock_id}")
                continue

            stock.articles.extend(stock_articles)
            status.stocks_cache[stock_id] = stock
            buzz_stocks.append(stock)

        status.buzz_stocks = buzz_stocks
        status.stats.buzz_qualified = len(buzz_stocks)
        self._logger.info(f"Buzz candidates: {status.stats.buzz_scanned} -> {status.stats.buzz_qualified}")
