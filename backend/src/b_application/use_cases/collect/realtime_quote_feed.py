from a_domain.model.market.stock import Stock
from a_domain.ports.market.price_provider import IRealtimeQuoteProvider
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.system.market_clock import IMarketClock
from b_application.config.app_config import AppConfig
from b_application.schemas.pipeline_status import PipelineStatus


class RealtimeQuoteFeed:
    """
    Gives each stock a realtime quote that can price an order.

    A stock whose quote is still fresh is not asked for again. A stock left without a fresh quote, because the
    fetch failed, the source had no trade or the quote is too old, joins status.stale_stock_ids.
    """

    def __init__(
        self, quote_provider: IRealtimeQuoteProvider, market_clock: IMarketClock, config: AppConfig, logger: ILoggingProvider
    ) -> None:
        self._quote_provider = quote_provider
        self._market_clock = market_clock
        self._quote_rule = config.freshness.realtime_quote_rule()
        self._logger = logger

    async def execute(self, stocks: list[Stock], status: PipelineStatus) -> None:
        asked_at = self._market_clock.now()
        unique_stocks = {stock.stock_id: stock for stock in stocks}.values()
        pending = [stock for stock in unique_stocks if self._quote_rule.apply(stock.realtime_bar, asked_at) is not None]

        if not pending:
            return

        fetch_failure: str | None = None

        try:
            quotes = await self._quote_provider.fetch_realtime_bars(pending)
        except Exception as error:
            self._logger.error(f"Failed to fetch realtime market data: {error}")
            status.stats.add_error(f"Failed to fetch realtime market data: {error}")
            quotes, fetch_failure = {}, "realtime fetch failed"

        now = self._market_clock.now()

        for stock in pending:
            stock.realtime_bar = quotes.get(stock.stock_id, stock.realtime_bar)
            reason = fetch_failure or self._quote_rule.apply(quotes.get(stock.stock_id), now)

            if reason is None:
                status.stale_stock_ids.discard(stock.stock_id)
                continue

            status.mark_stale(stock.stock_id)
            status.stats.log(f"Market data blocked: {stock.stock_id}, {reason}", now=now)
            self._logger.warning(f"Market data blocked: {stock.stock_id}, {reason}")
