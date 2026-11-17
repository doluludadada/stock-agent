from a_domain.model.system.stats import SystemStats
from a_domain.model.system.user import User
from a_domain.ports.market.daily_bar_matrix_provider import IDailyBarMatrixProvider
from a_domain.ports.system.market_clock import IMarketClock
from a_domain.ports.system.ordering_switch import IOrderingSwitch
from a_domain.ports.trading.execution_provider import IExecutionProvider, ISimulatedExecutionProvider
from a_domain.ports.trading.trading_journal import ITradingJournal
from a_domain.rules.trading.follow import FollowSchedule
from a_domain.types.enums import ExecutionProvider, FeatureVisibility, Workflow
from b_application.config.app_config import AppConfig


class RankingFollowSchedule:
    """
    Use Case: Where the user's schedule of the ranking follow stands now (FollowScheduleRule): the time they chose, the
    times the site offers, the account they chose and the accounts the site lets their follow order on now
    (RealBrokerGateRule, on the real broker's login as it reports itself and the site's ordering switch as it is now),
    the ranking's latest decision while no ranking follow of that account finished it under the active formula, the
    schedule's last follow that left it so, and whether the schedule follows it now. The ranking block and My settings
    show it, and the Web API's timer starts a follow when it is due. It reads the sessions of the ranking's history,
    none while the site holds no bar, so it answers on a site that can make no ranking yet; the user's ranking follows
    from the trading journal, on the mock account since it opened and on a real broker ever, which it returns oldest
    first, each naming its account, for the step that reads their return; and the clock. It reads no real broker's
    account, ranks nothing and never orders.
    """

    def __init__(
        self,
        journal: ITradingJournal,
        mock_broker: ISimulatedExecutionProvider,
        real_broker: IExecutionProvider | None,
        ordering_switch: IOrderingSwitch,
        matrix_provider: IDailyBarMatrixProvider,
        market_clock: IMarketClock,
        config: AppConfig,
    ) -> None:
        self._journal = journal
        self._mock_broker = mock_broker
        self._real_broker = real_broker
        self._ordering_switch = ordering_switch
        self._matrix_provider = matrix_provider
        self._market_clock = market_clock
        self._broker_rule = config.follow_broker_rule()
        self._schedule_rule = config.follow_schedule_rule()

    async def execute(self, user: User) -> tuple[FollowSchedule, list[SystemStats]]:
        account = await self._mock_broker.get_account()
        link = self._real_broker.link() if self._real_broker is not None else None
        follows: list[SystemStats] = []
        offered: list[ExecutionProvider] = []

        for broker in ExecutionProvider:
            ordering = await self._ordering_switch.visibility(broker) if broker.real else FeatureVisibility.OFF
            follows += await self._journal.runs_of(Workflow.RANKING_FOLLOW, broker, None if broker.real else account.opened_at)

            if self._broker_rule.apply(Workflow.RANKING_FOLLOW, broker, link, user, ordering) is None:
                offered.append(broker)

        follows.sort(key=lambda follow: follow.start_time)
        history = await self._matrix_provider.load_ranking_history()
        sessions = history.bars.sessions if history is not None else ()
        now = self._market_clock.to_market_datetime(self._market_clock.now())
        schedule = self._schedule_rule.apply(
            user.ranking_follow_time,
            sessions,
            follows,
            now,
            self._market_clock.trading_phase(),
            user.ranking_follow_broker,
            tuple(offered),
        )

        return schedule, follows
