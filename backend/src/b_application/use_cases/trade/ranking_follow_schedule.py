from collections.abc import Mapping

from a_domain.model.system.stats import SystemStats
from a_domain.model.system.user import User
from a_domain.ports.market.daily_bar_matrix_provider import IDailyBarMatrixProvider
from a_domain.ports.system.market_clock import IMarketClock
from a_domain.ports.system.ordering_switch import IOrderingSwitch
from a_domain.ports.trading.execution_provider import IExecutionProvider
from a_domain.ports.trading.trading_journal import ITradingJournal
from a_domain.rules.trading.follow import FollowAccount, FollowSchedule
from a_domain.types.enums import ExecutionProvider, Workflow
from b_application.config.app_config import AppConfig


class RankingFollowSchedule:
    """
    Use Case: The user's ranking follow as My settings and the ranking block show it, and as a follow asks it before
    it reads or orders: the user's follow account and the accounts the site offers them as one now
    (FollowAccountRule, on what the logins of `accounts`, the user's, report of themselves and the site's ordering
    switch as it is now); and where their schedule stands (FollowScheduleRule): the time they chose, the times the site
    offers, the ranking's latest decision while no ranking follow of the follow account finished it under the active
    formula, the schedule's last follow that left it so, and whether the schedule follows it now. It reads the sessions
    of the ranking's history, none while the site holds no bar, so it answers on a site that can make no ranking yet;
    the user's ranking follows from the trading journal, on the mock account since it opened while the site offers it
    to the user, whose book it reads for that alone, and on a real broker ever, of which it returns those that took a
    decision, oldest first, each naming its account and the formula it used; and the clock. It reads no position,
    ranks nothing and never orders.
    """

    def __init__(
        self,
        journal: ITradingJournal,
        accounts: Mapping[ExecutionProvider, IExecutionProvider],
        ordering_switch: IOrderingSwitch,
        matrix_provider: IDailyBarMatrixProvider,
        market_clock: IMarketClock,
        config: AppConfig,
    ) -> None:
        self._journal = journal
        self._accounts = accounts
        self._ordering_switch = ordering_switch
        self._matrix_provider = matrix_provider
        self._market_clock = market_clock
        self._account_rule = config.follow_account_rule()
        self._schedule_rule = config.follow_schedule_rule()

    async def execute(self, user: User) -> tuple[FollowAccount, FollowSchedule, list[SystemStats]]:
        links = {broker: account.link() for broker, account in self._accounts.items() if broker.real}
        follow_account = self._account_rule.apply(user, links, await self._ordering_switch.read())
        follows: list[SystemStats] = []

        for broker in ExecutionProvider:
            if broker.real:
                follows += await self._journal.runs_of(Workflow.RANKING_FOLLOW, broker, None)
            elif broker in follow_account.brokers:
                opened_at = (await self._accounts[broker].get_account()).opened_at
                follows += await self._journal.runs_of(Workflow.RANKING_FOLLOW, broker, opened_at)

        follows.sort(key=lambda follow: follow.start_time)
        history = await self._matrix_provider.load_ranking_history()
        sessions = history.bars.sessions if history is not None else ()
        now = self._market_clock.to_market_datetime(self._market_clock.now())
        schedule = self._schedule_rule.apply(
            user.ranking_follow_time, sessions, follows, now, self._market_clock.trading_phase(), follow_account
        )

        return (
            follow_account,
            schedule,
            [run for run in follows if run.ranking_formula is not None and run.ranking_decided_on is not None],
        )
