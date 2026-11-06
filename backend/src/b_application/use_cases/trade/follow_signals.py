from collections.abc import Mapping, Sequence

from a_domain.model.market.stock import Stock
from a_domain.model.system.stats import SystemStats
from a_domain.model.trading.account import Account
from a_domain.model.trading.signal import TradeSignal
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.system.market_clock import IMarketClock
from a_domain.ports.trading.trading_journal import ITradingJournal
from a_domain.rules.trading.follow import FollowRule


class FollowSignals:
    """
    Use Case: Decide the follow decision of each open decision (FollowRule) against one reading of the clock and
    record them as this run's decisions, so each order that follows has its decision saved first. A decision that gets
    none now is logged in the run and stays open. When the decisions cannot be saved, none is returned, so nothing is
    sent.
    """

    def __init__(self, journal: ITradingJournal, market_clock: IMarketClock, logger: ILoggingProvider) -> None:
        self._journal = journal
        self._market_clock = market_clock
        self._follow_rule = FollowRule()
        self._logger = logger

    async def execute(
        self, decisions: Sequence[TradeSignal], stocks: Mapping[str, Stock], account: Account, stats: SystemStats
    ) -> list[TradeSignal]:
        now = self._market_clock.now()
        follows: list[TradeSignal] = []

        for decision in decisions:
            follow = self._follow_rule.apply(decision, stocks.get(decision.stock_id), account.position_for(decision.stock_id), now)

            if isinstance(follow, str):
                stats.log(f"Not followed now: {decision.action} {decision.stock_id}, {follow}", now=now)
                continue

            follows.append(follow)

        try:
            await self._journal.save_signals(stats.run_id, follows)
        except Exception as error:
            self._logger.error(stats.add_error(f"Follow decisions not saved, so nothing was sent: {error}"))
            return []

        stats.signals_generated += len(follows)
        return follows
