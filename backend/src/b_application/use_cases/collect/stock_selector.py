"""
Use Case: Select stocks from watchlists and manual input.
Entry point of the intraday pipeline.
"""
from a_domain.model.market.stock import Stock
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.trading.watchlist_repository import IWatchlistRepository
from a_domain.types.enums import CandidateSource, SignalReason


class StockSelector:
    """
    Aggregates stocks from multiple sources.

    Priority (for deduplication):
    1. Manual Input (highest)
    2. Social Buzz
    3. Technical Watchlist (lowest)
    """

    def __init__(self, watchlist_repo: IWatchlistRepository, logger: ILoggingProvider):
        self._repo = watchlist_repo
        self._logger = logger

    async def execute(self, manual_symbols: list[str] | None = None) -> list[Stock]:
        stock_map: dict[str, Stock] = {}

        # 1. Manual Input (highest priority)
        if manual_symbols:
            self._logger.info(f"Processing manual input: {manual_symbols}")
            stocks = await self._repo.get_stocks_by_ids(manual_symbols)
            for stock in stocks:
                stock.source = CandidateSource.MANUAL_INPUT
                stock.trigger_reason = SignalReason.MANUAL_REQ
                stock_map[stock.stock_id] = stock

        # 2. Buzz Watchlist (hot data)
        buzz_items = await self._repo.get_buzz_watchlist()
        for stock, reason in buzz_items:
            if stock.stock_id not in stock_map:
                stock.source = CandidateSource.SOCIAL_BUZZ
                stock.trigger_reason = reason
                stock_map[stock.stock_id] = stock

        # 3. Technical Watchlist (cold data, skip if manual input provided)
        if not manual_symbols:
            daily_stocks = await self._repo.get_technical_watchlist()
            for stock in daily_stocks:
                if stock.stock_id not in stock_map:
                    stock.source = CandidateSource.TECHNICAL_WATCHLIST
                    stock.trigger_reason = "Daily Screen"
                    stock_map[stock.stock_id] = stock

        result = list(stock_map.values())
        self._logger.info(f"Selected {len(result)} stocks")
        return result
