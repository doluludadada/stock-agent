# backend/src/b_application/use_cases/collect/market_scan.py

from a_domain.model.market.stock import Stock
from a_domain.ports.market.social_media_provider import ISocialMediaProvider
from a_domain.ports.market.stock_provider import IStockProvider
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.trading.watchlist_repository import IWatchlistRepository
from a_domain.types.enums import CandidateSource
from b_application.schemas.config import AppConfig
from b_application.schemas.pipeline_context import PipelineContext


class MarketScan:
    def __init__(
        self,
        social_media_provider: ISocialMediaProvider,
        watchlist_repo: IWatchlistRepository,
        stock_provider: IStockProvider,
        logger: ILoggingProvider,
        config: AppConfig,
    ):
        self._social_media_provider = social_media_provider
        self._repo = watchlist_repo
        self._stock_provider = stock_provider
        self._logger = logger
        self._config = config

    async def execute(self, context: PipelineContext) -> None:
        self._logger.info("Scanning social media for trending stocks.")

        try:
            trending_articles = await self._social_media_provider.get_trending_stocks(
                limit=self._config.collect_rules.social_trending_limit
            )
            self._social_media_provider.save_social_media_data(trending_articles)

            if not trending_articles:
                return

            stock_map: dict[str, Stock] = {}

            for article in trending_articles:
                stock = stock_map.get(article.stock_id)

                if stock is None:
                    base_stock = await self._stock_provider.get_by_id(article.stock_id)

                    if base_stock is None:
                        self._logger.warning(f"Buzz stock not found in market universe: {article.stock_id}")

                        stock = Stock(
                            stock_id=article.stock_id,
                            source=CandidateSource.SOCIAL_BUZZ,
                            trigger_reason=article.title,
                        )
                    else:
                        stock = Stock(
                            stock_id=base_stock.stock_id,
                            market=base_stock.market,
                            name=base_stock.name,
                            industry=base_stock.industry,
                            source=CandidateSource.SOCIAL_BUZZ,
                            trigger_reason=article.title,
                        )

                    stock_map[article.stock_id] = stock

                stock.articles.append(article)

            stocks = list(stock_map.values())
            reasons = [stock.trigger_reason for stock in stocks]

            await self._repo.save_buzz_watchlist(stocks, reasons)

            context.buzz_watchlist = stocks

            self._logger.success(f"Updated Buzz Watchlist: {len(stocks)} stocks from {len(trending_articles)} articles.")

        except Exception as exc:
            self._logger.error(f"Failed to scan social media: {exc}")
