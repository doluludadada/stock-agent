from a_domain.model.market.stock import Stock
from a_domain.ports.market.social_media_provider import ISocialMediaProvider
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.trading.watchlist_repository import IWatchlistRepository
from a_domain.types.enums import CandidateSource
from b_application.schemas.config import AppConfig
from b_application.schemas.pipeline_context import PipelineContext


class MarketScan:
    def __init__(
        self,
        social_provider: ISocialMediaProvider,
        watchlist_repo: IWatchlistRepository,
        logger: ILoggingProvider,
        config: AppConfig,
    ):
        self._social = social_provider
        self._repo = watchlist_repo
        self._logger = logger
        self._config = config

    async def execute(self, workflow_state: PipelineContext) -> None:
        self._logger.info("Scanning social media for trending stocks...")

        try:
            trending_articles = await self._social.get_trending_stocks(
                limit=self._config.collect_rules.social_trending_limit
            )
            if not trending_articles:
                return

            trending_stocks: list[Stock] = []
            reasons: list[str] = []

            for article in trending_articles:
                stock = Stock(
                    stock_id=article.stock_id,
                    source=CandidateSource.SOCIAL_BUZZ,
                    trigger_reason=article.title,
                )
                stock.articles.append(article)
                trending_stocks.append(stock)
                reasons.append(article.title)

            await self._repo.save_buzz_watchlist(trending_stocks, reasons)
            workflow_state.buzz_watchlist = trending_stocks
            workflow_state.stats.total_scanned += len(trending_stocks)
            self._logger.success(f"Updated Buzz Watchlist with {len(trending_stocks)} stocks.")
        except Exception as e:
            self._logger.error(f"Trending scan failed: {e}")
            workflow_state.stats.add_error(str(e))
