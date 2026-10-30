from datetime import timedelta

from a_domain.model.market.stock import Stock
from a_domain.model.trading.watchlist import WatchlistAddition
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.system.market_clock import IMarketClock
from a_domain.ports.trading.watchlist_repository import IWatchlistRepository
from a_domain.rules.watchlist import WatchlistRule
from a_domain.types.enums import WatchlistType
from b_application.schemas.config import AppConfig


class WatchStocks:
    """Adds stocks to one watchlist type according to WatchlistRule."""

    def __init__(
        self, watchlist_repository: IWatchlistRepository, market_clock: IMarketClock, config: AppConfig, logger: ILoggingProvider
    ) -> None:
        self._watchlist_repository = watchlist_repository
        self._market_clock = market_clock
        self._rule = WatchlistRule(automatic_expiry=timedelta(hours=config.watchlist.automatic_expiry_hours))
        self._logger = logger

    async def execute(self, stocks: list[Stock], watchlist_type: WatchlistType) -> WatchlistAddition:
        active_entries = await self._watchlist_repository.get_active()
        addition = self._rule.add(active_entries, stocks, watchlist_type, self._market_clock.now())

        await self._watchlist_repository.save(addition.entries)

        for stock in addition.stocks:
            stock.watchlist_types.add(watchlist_type)

        self._logger.info(
            f"Watchlist updated. Type={watchlist_type.value}, "
            f"added={len(addition.added_stock_ids)}, already present={len(addition.already_present_stock_ids)}."
        )

        return addition
