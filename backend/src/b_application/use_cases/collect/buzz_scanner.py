from a_domain.model.market.stock import Stock
from a_domain.model.trading.watchlist import StockWatchlist
from a_domain.ports.market.social_media_provider import ISocialMediaProvider
from a_domain.ports.market.stock_provider import IStockProvider
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.types.enums import WatchlistType
from b_application.schemas.config import AppConfig
from b_application.schemas.pipeline_context import PipelineContext


class BuzzScanner:
    def __init__(
        self,
        social_media_provider: ISocialMediaProvider,
        stock_provider: IStockProvider,
        logger: ILoggingProvider,
        config: AppConfig,
    ):
        self._social = social_media_provider
        self._stock = stock_provider
        self._logger = logger
        self._config = config

    async def execute(self, context: PipelineContext) -> None:
        self._logger.info("Scanning social media for buzz...")
        try:
            articles = await self._social.get_trending_stocks(limit=self._config.collect_rules.social_trending_limit)
        except Exception as e:
            self._logger.error(f"Buzz scan failed: {e}")
            return

        if not articles:
            return

        self._social.save_social_media_data(articles)
        stocks_by_id: dict[str, Stock] = {}

        for article in articles:
            if article.stock_id not in stocks_by_id:
                stock = await self._stock.get_by_id(article.stock_id)
                if stock:
                    stock.trigger_reason = article.title
                    stocks_by_id[stock.stock_id] = stock

            if article.stock_id in stocks_by_id:
                stocks_by_id[article.stock_id].articles.append(article)

        buzz_stocks = list(stocks_by_id.values())
        watchlist_stock = [
            StockWatchlist(stock_id=stock.stock_id, type=WatchlistType.BUZZ)
            for stock in buzz_stocks
        ]

        context.all_stocks = buzz_stocks
        context.watchlist = watchlist_stock

        self._logger.info(f"Found {len(buzz_stocks)} trending stocks.")
