from collections.abc import Mapping

from a_domain.model.market.stock import Stock
from a_domain.model.system.stats import SystemStats
from a_domain.model.trading.account import Account
from a_domain.model.trading.signal import TradeSignal
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.system.market_clock import IMarketClock
from a_domain.ports.trading.trading_journal import ITradingJournal
from a_domain.rules.trading.ranking import Ranking
from b_application.config.app_config import AppConfig


class RankingFollowSignals:
    """
    Use Case: Decide what brings the account of the run's broker to the ranking (RankingFollowRule), on the account valued at the
    run's latest prices (AccountValueRule) and against one reading of the clock, and record the decisions as this run's,
    so each order that follows has its decision saved first. A stock that gets no decision now is logged in the run
    and stays open. When the decisions cannot be saved, none is returned, so nothing is sent.
    """

    def __init__(self, journal: ITradingJournal, market_clock: IMarketClock, config: AppConfig, logger: ILoggingProvider) -> None:
        self._journal = journal
        self._market_clock = market_clock
        self._value_rule = config.market.account_value_rule()
        self._follow_rule = config.ranking_follow_rule()
        self._logger = logger

    async def execute(self, ranking: Ranking, stocks: Mapping[str, Stock], account: Account, stats: SystemStats) -> list[TradeSignal]:
        now = self._market_clock.now()
        valued = self._value_rule.apply(account, stocks.values())
        decided = self._follow_rule.apply(ranking, valued, stocks, now, stats.execution_provider)
        follows = [decision for decision in decided if isinstance(decision, TradeSignal)]

        for unfollowed in decided:
            if isinstance(unfollowed, str):
                stats.log(f"Not followed now: {unfollowed}", now=now)

        try:
            await self._journal.save_signals(stats.run_id, follows)
        except Exception as error:
            self._logger.error(stats.add_error(f"Ranking follow decisions not saved, so nothing was sent: {error}"))
            return []

        stats.signals_generated += len(follows)
        return follows
