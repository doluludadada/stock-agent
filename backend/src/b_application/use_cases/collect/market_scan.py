from a_domain.ports.market.social_media_provider import ISocialMediaProvider
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.trading.watchlist_repository import IWatchlistRepository
from b_application.schemas.config import AppConfig
from b_application.schemas.pipeline_context import PipelineContext


class MarketScan:
    """Phase 2: Fetches trending Stock entities -> Saves to Buzz Watchlist (DB)."""

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

    async def execute(self, ctx: PipelineContext) -> None:
        self._logger.info("Scanning social media for trending stocks...")

        try:
            trending_stocks = await self._social.get_trending_stocks(
                limit=self._config.collect_rules.social_trending_limit
            )
            if not trending_stocks:
                return

            reasons = [stock.trigger_reason for stock in trending_stocks]

            await self._repo.save_buzz_watchlist(trending_stocks, reasons)
            ctx.buzz_watchlist = trending_stocks
            ctx.stats.total_scanned += len(trending_stocks)
            self._logger.success(f"Updated Buzz Watchlist with {len(trending_stocks)} stocks.")
        except Exception as e:
            self._logger.error(f"Trending scan failed: {e}")
            ctx.stats.add_error(str(e))
