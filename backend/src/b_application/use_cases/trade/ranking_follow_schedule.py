from a_domain.model.system.user import User
from a_domain.ports.system.market_clock import IMarketClock
from a_domain.ports.trading.execution_provider import ISimulatedExecutionProvider
from a_domain.ports.trading.trading_journal import ITradingJournal
from a_domain.rules.trading.follow import FollowSchedule
from a_domain.rules.trading.ranking import RankingHistory
from a_domain.types.enums import Workflow
from b_application.config.app_config import AppConfig


class RankingFollowSchedule:
    """
    Use Case: Where the user's schedule of the ranking follow stands now (FollowScheduleRule): the time they chose, the
    times the site offers, the ranking's latest decision while no ranking follow of their mock account took it, and
    whether the schedule follows it now. The ranking block shows it, and the Web API's timer starts a follow when it is
    due. It reads the history's sessions, the account's opening and its ranking follows from the trading journal, and
    the clock; it ranks nothing and never orders.
    """

    def __init__(
        self, journal: ITradingJournal, mock_broker: ISimulatedExecutionProvider, market_clock: IMarketClock, config: AppConfig
    ) -> None:
        self._journal = journal
        self._mock_broker = mock_broker
        self._market_clock = market_clock
        self._schedule_rule = config.follow_schedule_rule()

    async def execute(self, history: RankingHistory, user: User) -> FollowSchedule:
        account = await self._mock_broker.get_account()
        follows = await self._journal.runs_of(Workflow.RANKING_FOLLOW, self._mock_broker.link().broker, account.opened_at)
        now = self._market_clock.to_market_datetime(self._market_clock.now())

        return self._schedule_rule.apply(
            user.ranking_follow_time, history.bars.sessions, follows, now, self._market_clock.trading_phase()
        )
