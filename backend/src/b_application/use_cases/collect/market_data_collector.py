from a_domain.model.market.stock import Stock
from a_domain.model.system.stats import SystemStats
from a_domain.ports.market.daily_close_archive import IDailyCloseArchive
from a_domain.ports.market.price_provider import IPriceHistoryProvider
from a_domain.ports.market.stock_provider import IStockProvider
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.system.market_clock import IMarketClock
from a_domain.rules.collect.freshness import ArchiveWarmUpRule
from b_application.config.app_config import AppConfig


class MarketDataCollector:
    """
    Loads each stock's daily history, the input of technical analysis, and returns the stocks that have one. The
    window covers the strategy's required_bars in calendar days; a stock that still has fewer bars fails the strategy.

    History older than the history freshness limit is dropped, so that stock is not analysed. A stock in `skip` gets
    no history: Intraday skips the stocks its run may no longer act on. Realtime quotes, which price orders, are
    RealtimeQuoteFeed's job.

    With `official_change`, which the stock page asks for, the exchange's official change of the latest session goes
    onto each stock's daily bar of that session. Only the TWSE and TPEX listings report it, against the session's
    reference price; the daily history does not.

    `archive` is the open-data archive when the daily history comes from it (a public site), else None: while it holds
    fewer sessions than required_bars, the run says so instead of only failing every stock for too few bars.
    """

    def __init__(
        self,
        ohlcv_provider: IPriceHistoryProvider,
        stock_provider: IStockProvider,
        archive: IDailyCloseArchive | None,
        market_clock: IMarketClock,
        config: AppConfig,
        logger: ILoggingProvider,
    ) -> None:
        self._ohlcv_provider = ohlcv_provider
        self._stock_provider = stock_provider
        self._archive = archive
        self._warm_up = ArchiveWarmUpRule()
        self._market_clock = market_clock
        self._history_days = config.analysis.history_days
        self._history_freshness = config.freshness.history_rule()
        self._missing_session = config.freshness.missing_session_rule()
        self._logger = logger

    async def execute(
        self,
        stocks: list[Stock],
        required_bars: int,
        stats: SystemStats,
        *,
        skip: frozenset[str] = frozenset(),
        official_change: bool = False,
    ) -> list[Stock]:
        stocks = [stock for stock in stocks if stock.stock_id not in skip]
        self._logger.info(f"Fetching OHLCV data for {len(stocks)} stocks.")
        try:
            window = self._market_clock.history_window(self._history_days(required_bars))
            history = await self._ohlcv_provider.fetch_history(stocks, *window)
        except Exception as error:
            self._logger.error(stats.add_error(f"Failed to fetch market data: {error}"))
            return [stock for stock in stocks if stock.ohlcv]
        official = await self._stock_provider.get_latest_closes() if official_change else {}
        for stock in stocks:
            stock.load_history(history.get(stock.stock_id, []))
            last_session = self._market_clock.to_trading_date(stock.ohlcv[-1].ts) if stock.ohlcv else None
            if last_session is None:
                self._logger.warning(f"Market data unavailable: {stock.stock_id}")
            elif not self._history_freshness.apply(last_session, self._market_clock.today()):
                message = f"Technical analysis blocked: {stock.stock_id}, stale daily history: last bar {last_session.isoformat()}"
                stats.stale_market_data_count += 1
                stats.log(message, now=self._market_clock.now())
                self._logger.warning(message)
                stock.ohlcv = []
            if (close := official.get(stock.stock_id)) is not None:
                stock.take_official_change(close)
        last_sessions = {
            stock.stock_id: (stock.market, self._market_clock.to_trading_date(stock.ohlcv[-1].ts)) for stock in stocks if stock.ohlcv
        }
        warm_up = self._warm_up.apply(await self._archive.session_count(), required_bars) if self._archive else None
        for problem in filter(None, (warm_up, self._missing_session.apply(last_sessions, self._market_clock.last_settled_session()))):
            self._logger.warning(stats.add_error(problem))
        self._logger.success(f"Collected market data for {len(last_sessions)}/{len(stocks)} stocks.")
        return [stock for stock in stocks if stock.ohlcv]
