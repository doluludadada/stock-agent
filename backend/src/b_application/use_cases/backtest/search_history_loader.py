from a_domain.ports.market.daily_bar_matrix_provider import IDailyBarMatrixProvider
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.system.market_clock import IMarketClock
from a_domain.rules.technical.search import SearchHistory
from a_domain.rules.technical.strategy import TechnicalStrategy
from a_domain.rules.trading.backtest import BacktestPeriodRule
from a_domain.types.errors import BacktestPeriodUnavailable
from b_application.config.app_config import AppConfig


class SearchHistoryLoader:
    """
    The daily history a strategy search reads, as it starts: every listed stock's held history as one matrix, and the
    sessions from the first one that a strategy of strategy_search.max_required_bars daily bars, or of the origin's when
    it needs more, can be scored on (BacktestPeriodRule), split in time order into train, validation and the holdout
    (SessionSplitRule). BacktestPeriodUnavailable while the history is too short.
    """

    def __init__(
        self, matrix_provider: IDailyBarMatrixProvider, market_clock: IMarketClock, config: AppConfig, logger: ILoggingProvider
    ) -> None:
        self._matrix_provider = matrix_provider
        self._market_clock = market_clock
        self._history_days = config.analysis.history_days
        self._max_required_bars = config.strategy_search.max_required_bars
        self._period_rule = BacktestPeriodRule()
        self._split_rule = config.strategy_search.split_rule()
        self._logger = logger

    async def execute(self, origin: TechnicalStrategy) -> SearchHistory:
        started_at = self._market_clock.now()
        bars = await self._matrix_provider.load()
        history_days = self._history_days(max(self._max_required_bars, origin.required_bars))
        period = self._period_rule.apply(bars.sessions[0], bars.sessions[-1], history_days) if bars is not None else None

        if bars is None or period is None:
            raise BacktestPeriodUnavailable(f"No strategy search can run yet: it reads {history_days} days of history first.")

        spans = self._split_rule.apply(bars.sessions, period[0])
        described = ", ".join(f"{span} {first} to {last}" for span, (first, last) in spans.items())
        self._logger.info(f"Strategy search over {len(bars.stock_ids)} stocks: {described}")

        return SearchHistory(started_at=started_at, bars=bars, spans=spans)
