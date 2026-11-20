from collections.abc import Mapping

from a_domain.model.market.stock import Stock
from a_domain.model.system.stats import SystemStats
from a_domain.model.trading.account import Account
from a_domain.model.trading.signal import TradeSignal
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.system.market_clock import IMarketClock
from a_domain.ports.trading.execution_provider import IExecutionProvider
from a_domain.ports.trading.trading_journal import ITradingJournal
from a_domain.rules.trading.ranking import Ranking
from a_domain.types.enums import Workflow
from b_application.config.app_config import AppConfig


class RankingFollowSignals:
    """
    Use Case: Decide what brings the account of the run's broker to the ranking (RankingFollowRule), on the account valued
    at the run's latest prices (AccountValueRule) and against one reading of the clock, and record the decisions as this
    run's, so each order that follows has its decision saved first. On a real broker the decisions stay inside its BUY
    limits, which follow that equity, after the day's BUYs on it in the journal, and inside the broker's own trading
    limit where it says one (IExecutionProvider.trading_available). The account's ranking follows in the journal, since
    the mock account opened and ever on a real broker, say whether this is the first follow after a switch of the active
    formula, which tops up the ranked stocks the account holds. A stock that gets no decision now is logged in the run
    and stays open. It returns the equity, which the run's order gates hold its BUYs to, and the decisions; when
    they cannot be saved, none, so nothing is sent.
    """

    def __init__(
        self,
        journal: ITradingJournal,
        execution_provider: IExecutionProvider,
        market_clock: IMarketClock,
        config: AppConfig,
        logger: ILoggingProvider,
    ) -> None:
        self._journal = journal
        self._execution_provider = execution_provider
        self._market_clock = market_clock
        self._value_rule = config.market.account_value_rule()
        self._follow_rule = config.ranking_follow_rule()
        self._logger = logger

    async def execute(
        self, ranking: Ranking, stocks: Mapping[str, Stock], account: Account, stats: SystemStats
    ) -> tuple[float, list[TradeSignal]]:
        now, broker = self._market_clock.now(), stats.execution_provider
        valued = self._value_rule.apply(account, stocks.values())
        day_start = self._market_clock.to_market_datetime(now).replace(hour=0, minute=0, second=0, microsecond=0)
        earlier_buys = await self._journal.buy_orders(broker, day_start) if broker.real else []
        trading_available = await self._execution_provider.trading_available()
        earlier_follows = await self._journal.runs_of(Workflow.RANKING_FOLLOW, broker, account.opened_at)
        decided = self._follow_rule.apply(ranking, valued, stocks, now, broker, earlier_buys, trading_available, earlier_follows)
        follows = [decision for decision in decided if isinstance(decision, TradeSignal)]

        for unfollowed in decided:
            if isinstance(unfollowed, str):
                stats.log(f"Not followed now: {unfollowed}", now=now)

        try:
            await self._journal.save_signals(stats.run_id, follows)
        except Exception as error:
            self._logger.error(stats.add_error(f"Ranking follow decisions not saved, so nothing was sent: {error}"))
            return valued.equity, []

        stats.signals_generated += len(follows)
        return valued.equity, follows
