from collections.abc import Mapping
from datetime import date

from a_domain.model.system.user import User
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.system.market_clock import IMarketClock
from a_domain.ports.system.ordering_switch import IOrderingSwitch
from a_domain.ports.system.user_store import IUserStore
from a_domain.ports.trading.execution_provider import IExecutionProvider
from a_domain.types.enums import ExecutionProvider, Feature, FollowAccountRefusal, UserStatus
from a_domain.types.ids import UserId
from b_application.config.app_config import AppConfig


class ScheduledFollowers:
    """
    The users whose scheduled ranking follow may run now, for the Web API's timer: the active users whose schedule is
    on and whose time has come today, while the market is in the phase this site places an order in (FollowTimeRule),
    whom the site shows the ranking, and to whom it offers their follow account now (FollowAccountRule, on what the
    logins of `accounts`, the site's, report of themselves and the site's ordering switch, read once per look and only
    while a user is due). A user it does not offer theirs is followed on no account, and why is logged once per user,
    day and refusal, since the timer looks every minute. The timer asks this again right before it starts a user's
    follow, so a user who turned the schedule off or changed their follow account meanwhile is not followed. It reads
    no position and ranks nothing: whether a user's follow is due is RankingFollowSchedule's answer, on that user's
    own Pipeline.
    """

    def __init__(
        self,
        user_store: IUserStore,
        accounts: Mapping[ExecutionProvider, IExecutionProvider],
        ordering_switch: IOrderingSwitch,
        market_clock: IMarketClock,
        config: AppConfig,
        logger: ILoggingProvider,
    ) -> None:
        self._user_store = user_store
        self._accounts = accounts
        self._ordering_switch = ordering_switch
        self._market_clock = market_clock
        self._features = config.features
        self._time_rule = config.follow_time_rule()
        self._account_rule = config.follow_account_rule()
        self._logged: dict[UserId, tuple[date, FollowAccountRefusal]] = {}
        self._logger = logger

    async def execute(self) -> list[User]:
        now, phase = self._market_clock.to_market_datetime(self._market_clock.now()), self._market_clock.trading_phase()
        due = [
            user
            for user in await self._user_store.users()
            if user.status == UserStatus.ACTIVE
            and self._time_rule.apply(user.ranking_follow_time, now, phase)
            and self._features.visibility(Feature.RANKING).shown_to(user.permissions)
        ]
        links = {broker: account.link() for broker, account in self._accounts.items() if broker.real}
        ordering = await self._ordering_switch.read() if due else None
        followers: list[User] = []

        for user in due:
            refusal = self._account_rule.apply(user, links, ordering).refusal

            if refusal is None:
                followers.append(user)
                continue

            if self._logged.get(user.user_id) != (now.date(), refusal):
                self._logged[user.user_id] = now.date(), refusal
                account = user.ranking_follow_broker.label
                self._logger.info(f"The scheduled ranking follow of user {user.user_id} on {account} does nothing now: {refusal}.")

        return followers
