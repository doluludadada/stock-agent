from backend.src.a_domain.model.system.stats import SystemStats
from backend.src.a_domain.ports.input.social_media_provider import ISocialMediaProvider
from backend.src.a_domain.ports.input.watchlist_repository import IWatchlistRepository
from backend.src.a_domain.ports.system.logging_provider import ILoggingProvider


class MarketScan:
    """
    Phase 2: Fetches from Provider (Web) -> Saves to Buzz Watchlist (DB).
    """

    def __init__(
        self,
        social_provider: ISocialMediaProvider,
        watchlist_repo: IWatchlistRepository,
        logger: ILoggingProvider,
        # TODO: It should be set in config.yaml
        limit: int = 10,
    ):
        self._social = social_provider
        self._repo = watchlist_repo
        self._logger = logger
        self._limit = limit

    async def execute(self) -> SystemStats:
        stats = SystemStats()
        self._logger.info("Scanning social media for trending stocks...")

        try:
            # 1. Fetch from External World (Provider)
            trends = await self._social.get_trending_stocks(limit=self._limit)

            if not trends:
                return stats

            stock_ids = [t[0] for t in trends]
            stocks = await self._repo.get_stocks_by_ids(stock_ids)

            # 2. Save to Internal Storage (Repository)
            reasons = [t[1] for t in trends]
            await self._repo.save_buzz_watchlist(stocks, reasons)

            stats.total_candidates = len(stocks)
            self._logger.success(f"Updated Buzz Watchlist with {len(stocks)} stocks.")

        except Exception as e:
            self._logger.error(f"Trending scan failed: {e}")
            stats.add_error(str(e))

        return stats


