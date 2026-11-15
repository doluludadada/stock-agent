from a_domain.model.system.stats import SystemStats
from a_domain.model.system.user import User
from a_domain.ports.market.daily_bar_matrix_provider import IDailyBarMatrixProvider
from a_domain.ports.system.market_clock import IMarketClock
from a_domain.ports.trading.execution_provider import ISimulatedExecutionProvider
from a_domain.ports.trading.trading_journal import ITradingJournal
from a_domain.rules.trading.follow import FollowSchedule
from a_domain.types.enums import Workflow
from b_application.config.app_config import AppConfig


class RankingFollowSchedule:
    """
    Use Case: Where the user's schedule of the ranking follow stands now (FollowScheduleRule): the time they chose, the
    times the site offers, the ranking's latest decision while no ranking follow of their mock account finished it
    under the active formula, the schedule's last follow that left it so, and whether the schedule follows it now. The
    ranking block and My settings show it, and the Web API's timer starts a follow when it is due. It reads the
    sessions of the ranking's history, none while the site holds no bar, so it answers on a site that can make no
    ranking yet; the account's opening and its ranking follows since, from the trading journal, which it returns
    oldest first for the step that reads their return; and the clock. It ranks nothing and never orders.
    """

    def __init__(
        self,
        journal: ITradingJournal,
        mock_broker: ISimulatedExecutionProvider,
        matrix_provider: IDailyBarMatrixProvider,
        market_clock: IMarketClock,
        config: AppConfig,
    ) -> None:
        self._journal = journal
        self._mock_broker = mock_broker
        self._matrix_provider = matrix_provider
        self._market_clock = market_clock
        self._schedule_rule = config.follow_schedule_rule()

    async def execute(self, user: User) -> tuple[FollowSchedule, list[SystemStats]]:
        account = await self._mock_broker.get_account()
        follows = await self._journal.runs_of(Workflow.RANKING_FOLLOW, self._mock_broker.link().broker, account.opened_at)
        history = await self._matrix_provider.load_ranking_history()
        sessions = history.bars.sessions if history is not None else ()
        now = self._market_clock.to_market_datetime(self._market_clock.now())
        schedule = self._schedule_rule.apply(user.ranking_follow_time, sessions, follows, now, self._market_clock.trading_phase())

        return schedule, follows
