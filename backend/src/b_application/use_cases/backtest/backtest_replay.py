import asyncio
from time import perf_counter

from a_domain.model.trading.backtest import Backtest, BacktestInputs
from a_domain.ports.market.price_provider import IOhlcvProvider
from a_domain.ports.market.stock_provider import IStockProvider
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.system.market_clock import IMarketClock
from a_domain.rules.technical.matrix import DailyBarMatrix, StrategyScores
from a_domain.rules.technical.strategy import TechnicalStrategy
from a_domain.types.enums import MarketIndex
from b_application.config.app_config import AppConfig


class BacktestReplay:
    """
    Replays the live trading rules day by day on `scores` alone (BacktestRule), from `inputs.first` on an account of
    `inputs.initial_cash`, and returns the backtest, unsaved, with the TAIEX over the same sessions. The fees, the tax,
    the stop-loss and the risk per trade are the live settings; the two scores are the backtest's own. It reads no
    account, asks no AI and places no order.

    The replay is computation alone, so it runs in a worker thread and the Web API keeps answering meanwhile.
    """

    def __init__(
        self,
        stock_provider: IStockProvider,
        ohlcv_provider: IOhlcvProvider,
        market_clock: IMarketClock,
        config: AppConfig,
        logger: ILoggingProvider,
    ) -> None:
        self._stock_provider = stock_provider
        self._ohlcv_provider = ohlcv_provider
        self._market_clock = market_clock
        self._backtest_rule = config.backtest_rule
        self._stop_loss_pct = config.analysis.stop_loss_pct
        self._risk_per_trade_pct = config.analysis.risk_per_trade_pct
        self._logger = logger

    async def execute(
        self, strategy: TechnicalStrategy, inputs: BacktestInputs, bars: DailyBarMatrix, scores: StrategyScores
    ) -> Backtest:
        started = perf_counter()
        names = {stock.stock_id: stock.name for stock in await self._stock_provider.get_all()}
        rule, close = self._backtest_rule(inputs.buy_score, inputs.sell_score), self._market_clock.session_close
        curve, trades = await asyncio.to_thread(rule.apply, bars, scores, names, inputs.first, inputs.initial_cash, close)
        first, last = next(iter(curve)), next(reversed(curve))
        self._logger.info(
            f"Backtest replay of {strategy.strategy_id} from {first} to {last}: {len(curve)} sessions, {len(trades)} trades, "
            f"{perf_counter() - started:.2f}s"
        )

        return Backtest(
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
