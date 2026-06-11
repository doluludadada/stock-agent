from a_domain.model.market.stock import Stock
from a_domain.ports.market.social_media_provider import ISocialMediaProvider
from a_domain.ports.market.stock_provider import IStockProvider
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.types.enums import WatchlistType
from b_application.schemas.config import AppConfig
from b_application.schemas.pipeline_context import PipelineContext


# TODO: needa check
class BuzzScanner:
    def __init__(
        self,
        social_media_provider: ISocialMediaProvider,
        stock_provider: IStockProvider,
        logger: ILoggingProvider,
        config: AppConfig,
    ) -> None:
        self._social = social_media_provider
        self._stock = stock_provider
        self._logger = logger
        self._config = config

    async def execute(self, context: PipelineContext) -> None:
        self._logger.info("Scanning social media for buzz...")

        # Fetch articles
        articles = await self._social.get_trending_stocks(limit=self._config.collect_rules.social_trending_limit)
        if not articles:
            self._logger.info("No buzz articles found.")
            return

        self._social.save_social_media_data(articles)

        stocks: dict[str, Stock] = {}
        """
        stock_id, Stock
        """
        for article in articles:
            stock = stocks.get(article.stock_id)

            if stock is None:
                stock = context.stocks_cache.get(article.stock_id)
            # Backup logic might not need it.
            if stock is None:
                stock = await self._stock.get_by_id(article.stock_id)

            if stock is None:
                self._logger.warning(f"Buzz stock not found: {article.stock_id}")
                continue

            stock.candidate_source = WatchlistType.BUZZ
            stock.articles.append(article)

            stocks[stock.stock_id] = stock
            context.stocks_cache[stock.stock_id] = stock

        context.buzz_stocks = list(stocks.values())

        self._logger.info(f"Found {len(context.buzz_stocks)} buzz candidates.")
