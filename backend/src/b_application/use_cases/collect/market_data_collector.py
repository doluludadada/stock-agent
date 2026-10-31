from a_domain.model.market.stock import Stock
from a_domain.ports.market.price_provider import IOhlcvProvider
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.system.market_clock import IMarketClock
from b_application.config.app_config import AppConfig
from b_application.schemas.pipeline_status import PipelineStatus


class MarketDataCollector:
    """
    Loads each stock's daily history, the input of technical analysis.

    History older than the history freshness limit is dropped, so that stock is not analysed. Realtime quotes,
    which price orders, are RealtimeQuoteFeed's job.
    """

    def __init__(
        self, ohlcv_provider: IOhlcvProvider, market_clock: IMarketClock, config: AppConfig, logger: ILoggingProvider
    ) -> None:
        self._ohlcv_provider = ohlcv_provider
        self._market_clock = market_clock
        self._lookback_days = config.analysis.lookback_days
        self._history_freshness = config.freshness.history_rule()
        self._missing_session = config.freshness.missing_session_rule()
        self._logger = logger

    async def execute(self, stocks: list[Stock], status: PipelineStatus) -> None:
        self._logger.info(f"Fetching OHLCV data for {len(stocks)} stocks.")

        try:
            history = await self._ohlcv_provider.fetch_history(stocks, *self._market_clock.history_window(self._lookback_days))
        except Exception as error:
            self._logger.error(f"Failed to fetch market data: {error}")
            status.stats.add_error(f"Failed to fetch market data: {error}")
            return

        for stock in stocks:
            stock.load_history(history.get(stock.stock_id, []))
            last_session = self._market_clock.to_trading_date(stock.ohlcv[-1].ts) if stock.ohlcv else None

            if last_session is None:
                self._logger.warning(f"Market data unavailable: {stock.stock_id}")
            elif not self._history_freshness.apply(last_session, self._market_clock.today()):
                message = f"Technical analysis blocked: {stock.stock_id}, stale daily history: last bar {last_session.isoformat()}"
                status.stats.stale_market_data_count += 1
                status.stats.log(message, now=self._market_clock.now())
                self._logger.warning(message)
                stock.ohlcv = []

        last_sessions = {stock.stock_id: self._market_clock.to_trading_date(stock.ohlcv[-1].ts) for stock in stocks if stock.ohlcv}

        if missing_session := self._missing_session.apply(last_sessions, self._market_clock.last_settled_session()):
            self._logger.warning(missing_session)
            status.stats.add_error(missing_session)

        self._logger.success(f"Collected market data for {len(last_sessions)}/{len(stocks)} stocks.")
