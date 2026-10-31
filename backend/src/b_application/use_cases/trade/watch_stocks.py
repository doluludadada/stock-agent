from a_domain.model.market.stock import Stock
from a_domain.model.trading.watchlist_addition import WatchlistAddition
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.system.market_clock import IMarketClock
from a_domain.ports.trading.watchlist_repository import IWatchlistRepository
from a_domain.rules.watchlist import WatchlistRule
from a_domain.types.enums import WatchlistType
from b_application.config.app_config import AppConfig


class WatchStocks:
    """
    Adds stocks to one watchlist type according to WatchlistRule. An automatic entry stays active through the close
    of the `watchlist.automatic_expiry_sessions`-th trading session that opens after its workflow last selected it.
    """

    def __init__(
        self, watchlist_repository: IWatchlistRepository, market_clock: IMarketClock, config: AppConfig, logger: ILoggingProvider
    ) -> None:
        self._watchlist_repository = watchlist_repository
        self._market_clock = market_clock
        self._automatic_expiry_sessions = config.watchlist.automatic_expiry_sessions
        self._logger = logger

    async def execute(self, stocks: list[Stock], watchlist_type: WatchlistType) -> WatchlistAddition:
        active_entries = await self._watchlist_repository.get_active()
        now = self._market_clock.now()
        automatic_expires_at = self._market_clock.session_close_after(now, self._automatic_expiry_sessions)
        addition = WatchlistRule.add(active_entries, stocks, watchlist_type, now, automatic_expires_at)

        await self._watchlist_repository.save(addition.entries)

        for stock in addition.stocks:
            stock.watchlist_types.add(watchlist_type)

        self._logger.info(
            f"Watchlist updated. Type={watchlist_type.value}, "
            f"added={len(addition.added_stock_ids)}, already present={len(addition.already_present_stock_ids)}."
        )

        return addition
