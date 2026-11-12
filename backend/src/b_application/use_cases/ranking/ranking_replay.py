import asyncio
from datetime import date
from time import perf_counter

from a_domain.ports.market.stock_provider import IStockProvider
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.rules.trading.ranking import RankingHistory
from a_domain.rules.trading.ranking_backtest import RankingBacktest
from b_application.config.app_config import AppConfig


class RankingReplay:
    """
    Replays the monthly ranking from `first` to `last` on the history (RankingBacktestRule), each ranked stock with its
    name in the exchange listing, at the live fee and tax. It reads no account, asks no AI and places no order.
    BacktestPeriodUnavailable for a period without a decision session.

    The replay is computation alone, so it runs in a worker thread and the Web API keeps answering meanwhile.
    """

    def __init__(self, stock_provider: IStockProvider, config: AppConfig, logger: ILoggingProvider) -> None:
        self._stock_provider = stock_provider
        self._replay_rule = config.ranking_backtest_rule()
        self._logger = logger

    async def execute(self, history: RankingHistory, first: date, last: date) -> RankingBacktest:
        started = perf_counter()
        names = {stock.stock_id: stock.name for stock in await self._stock_provider.get_all()}
        backtest = await asyncio.to_thread(self._replay_rule.apply, history, names, first, last)
        self._logger.info(
            f"Ranking backtest from {first} to {last}: {len(backtest.equity_curve)} sessions, {len(backtest.rankings)} decisions, "
            f"{perf_counter() - started:.1f}s"
        )

        return backtest
