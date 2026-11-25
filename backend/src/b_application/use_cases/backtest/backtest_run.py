import asyncio
from time import perf_counter

from a_domain.model.trading.backtest import Backtest, BacktestInputs
from a_domain.ports.market.daily_bar_matrix_provider import IDailyBarMatrixProvider
from a_domain.ports.market.price_provider import IPriceHistoryProvider
from a_domain.ports.market.stock_provider import IStockProvider
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.system.market_clock import IMarketClock
from a_domain.ports.trading.backtest_repository import IBacktestRepository
from a_domain.rules.technical.matrix import StrategyScoresRule
from a_domain.rules.technical.strategy import TechnicalStrategy
from a_domain.rules.trading.backtest import BacktestHistoryRule, BacktestPeriodRule
from a_domain.types.enums import MarketIndex
from a_domain.types.errors import BacktestPeriodUnavailable
from b_application.config.app_config import AppConfig


class BacktestRun:
    """
    Backtests `strategy` over the sessions `inputs` name, and returns the backtest saved for its user beside the user's
    newest accounts.saved_backtests, so runs can be compared. It scores every listed stock on every session the
    backtest reads: the held daily history from the first session's history window on (BacktestHistoryRule), and the
    strategy's score and verdict of each stock on each session over the window a run would read that day
    (StrategyScoresRule). It then replays the live trading rules day by day on those scores alone (BacktestRule), from
    `inputs.first` on an account of `inputs.initial_cash`, with the TAIEX over the same sessions. The fees, the tax, the
    stop-loss and the risk per trade are the live settings; the two scores are the backtest's own. It fetches no
    session the history lacks: a period outside the held sessions raises BacktestPeriodUnavailable, which says what may
    be covered. It reads no account, asks no AI and places no order.

    The scores and the replay are seconds of computation, so each runs in a worker thread and the Web API keeps
    answering meanwhile.
    """

    def __init__(
        self,
        matrix_provider: IDailyBarMatrixProvider,
        stock_provider: IStockProvider,
        ohlcv_provider: IPriceHistoryProvider,
        backtest_repository: IBacktestRepository,
        market_clock: IMarketClock,
        config: AppConfig,
        logger: ILoggingProvider,
    ) -> None:
        self._matrix_provider = matrix_provider
        self._stock_provider = stock_provider
        self._ohlcv_provider = ohlcv_provider
        self._backtest_repository = backtest_repository
        self._keep = config.accounts.saved_backtests
        self._market_clock = market_clock
        self._history_days = config.analysis.history_days
        self._history_rule = BacktestHistoryRule(period_rule=BacktestPeriodRule())
        self._backtest_rule = config.backtest_rule
        self._stop_loss_pct = config.analysis.stop_loss_pct
        self._risk_per_trade_pct = config.analysis.risk_per_trade_pct
        self._logger = logger

    async def execute(self, strategy: TechnicalStrategy, inputs: BacktestInputs) -> Backtest:
        started = perf_counter()
        bars = await self._matrix_provider.load()

        if bars is None:
            raise BacktestPeriodUnavailable("No backtest can run yet: the daily history holds no session.")

        history_days = self._history_days(strategy.required_bars)
        history, window_starts = self._history_rule.apply(bars, inputs.first, inputs.last, history_days)
        loaded = perf_counter()
        scores = await asyncio.to_thread(StrategyScoresRule(strategy=strategy).apply, history, window_starts)
        scored = perf_counter()
        self._logger.info(
            f"Backtest scores of {strategy.strategy_id}: {len(history.stock_ids)} stocks x {len(history.sessions)} sessions; "
            f"history {loaded - started:.2f}s, scores {scored - loaded:.2f}s"
        )

        names = {stock.stock_id: stock.name for stock in await self._stock_provider.get_all()}
        rule, close = self._backtest_rule(inputs.buy_score, inputs.sell_score), self._market_clock.session_close
        curve, trades = await asyncio.to_thread(rule.apply, history, scores, names, inputs.first, inputs.initial_cash, close)
        first, last = next(iter(curve)), next(reversed(curve))
        self._logger.info(
            f"Backtest replay of {strategy.strategy_id} from {first} to {last}: {len(curve)} sessions, {len(trades)} trades, "
            f"{perf_counter() - scored:.2f}s"
        )

        backtest = Backtest(
            created_at=self._market_clock.now(),
            strategy_id=strategy.strategy_id,
            strategy_name=strategy.name,
            inputs=inputs,
            stop_loss_pct=self._stop_loss_pct,
            risk_per_trade_pct=self._risk_per_trade_pct,
            equity_curve=curve,
            benchmark=await self._ohlcv_provider.fetch_index_history(MarketIndex.TAIEX, close(first), close(last)),
            trades=trades,
        )
        await self._backtest_repository.save(backtest, self._keep)

        return backtest
