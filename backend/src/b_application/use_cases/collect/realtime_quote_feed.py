from a_domain.model.market.stock import Stock
from a_domain.model.system.stats import SystemStats
from a_domain.ports.market.price_provider import IRealtimeQuoteProvider
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.system.market_clock import IMarketClock
from b_application.config.app_config import AppConfig


class RealtimeQuoteFeed:
    """
    Gives each stock a realtime quote that can price an order.

    A stock whose quote is still fresh is not asked for again. It returns the run's stale stocks after this refresh: a
    stock left without a fresh quote, because the fetch failed, the source had no trade or the quote is too old, joins
    them and counts once in stats.stale_market_data_count while it stays; a stock that got a fresh quote leaves them.
    """

    def __init__(
        self, quote_provider: IRealtimeQuoteProvider, market_clock: IMarketClock, config: AppConfig, logger: ILoggingProvider
    ) -> None:
        self._quote_provider = quote_provider
        self._market_clock = market_clock
        self._quote_rule = config.freshness.realtime_quote_rule()
        self._logger = logger

    async def execute(self, stocks: list[Stock], stale_stock_ids: set[str], stats: SystemStats) -> set[str]:
        asked_at = self._market_clock.now()
        unique_stocks = {stock.stock_id: stock for stock in stocks}.values()
        pending = [stock for stock in unique_stocks if self._quote_rule.apply(stock.realtime_bar, asked_at) is not None]

        if not pending:
            return set(stale_stock_ids)

        fetch_failure: str | None = None

        try:
            quotes = await self._quote_provider.fetch_realtime_bars(pending)
        except Exception as error:
            self._logger.error(stats.add_error(f"Failed to fetch realtime market data: {error}"))
            quotes, fetch_failure = {}, "realtime fetch failed"

        now = self._market_clock.now()
        blocked: set[str] = set()

        for stock in pending:
            stock.realtime_bar = quotes.get(stock.stock_id, stock.realtime_bar)

            if reason := fetch_failure or self._quote_rule.apply(quotes.get(stock.stock_id), now):
                blocked.add(stock.stock_id)
                stats.log(f"Market data blocked: {stock.stock_id}, {reason}", now=now)
                self._logger.warning(f"Market data blocked: {stock.stock_id}, {reason}")

        stats.stale_market_data_count += len(blocked - stale_stock_ids)

        return (stale_stock_ids - {stock.stock_id for stock in pending}) | blocked
