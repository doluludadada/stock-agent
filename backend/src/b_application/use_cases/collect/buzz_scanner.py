from a_domain.model.market.stock import Stock
from a_domain.ports.market.social_media_provider import ISocialMediaProvider
from a_domain.ports.market.stock_provider import IStockProvider
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.types.enums import WatchlistType
from b_application.schemas.config import AppConfig
from b_application.schemas.pipeline_status import PipelineStatus


class BuzzScanner:
    """
    Loads social-buzz stocks and attaches their buzz articles.
    """

    def __init__(
        self,
        social_media_provider: ISocialMediaProvider,
        stock_provider: IStockProvider,
        logger: ILoggingProvider,
        config: AppConfig,
    ) -> None:
        self._social_media_provider = social_media_provider
        self._stock_provider = stock_provider
        self._logger = logger
        self._social_trending_limit = config.collect_rules.social_trending_limit

    async def execute(self, status: PipelineStatus) -> None:
        self._logger.info("Scanning social media for buzz...")

        try:
            articles = await self._social_media_provider.get_trending_stocks(
                limit=self._social_trending_limit,
            )

            if not articles:
                self._logger.info("No buzz articles found.")
                return

            self._social_media_provider.save_social_media_data(articles)

            buzz_stocks: dict[str, Stock] = {}

            for article in articles:
                stock = status.stocks_cache.get(article.stock_id)

                if stock is None:
                    stock = await self._stock_provider.get_by_id(article.stock_id)

                if stock is None:
                    self._logger.warning(f"Buzz stock not found: {article.stock_id}")
                    continue

                stock.candidate_source = WatchlistType.BUZZ
                stock.articles.append(article)

                buzz_stocks[stock.stock_id] = stock
                status.stocks_cache[stock.stock_id] = stock

            status.buzz_stocks = list(buzz_stocks.values())
            status.stats.buzz_scanned = len(status.buzz_stocks)

            self._logger.info(f"Found {len(status.buzz_stocks)} buzz candidates.")

        except Exception as error:
            message = f"Failed to scan social buzz: {error}"
            self._logger.error(message)
            status.stats.add_error(message)