from datetime import date

from a_domain.model.system.user import User
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.system.market_clock import IMarketClock
from a_domain.ports.system.ordering_switch import IOrderingSwitch
from a_domain.ports.system.user_store import IUserStore
from a_domain.ports.trading.execution_provider import IExecutionProvider
from a_domain.types.enums import Feature, FeatureVisibility, UserStatus, Workflow
from a_domain.types.ids import UserId
from b_application.config.app_config import AppConfig


class ScheduledFollowers:
    """
    The users whose scheduled ranking follow may run now, for the Web API's timer: the active users whose schedule is
    on and whose time has come today, while the market is in the phase this site places an order in (FollowTimeRule),
    and whom the site shows both the ranking and ordering on the account their schedule chose, as the button's route
    requires. A schedule on a real broker needs more (RealBrokerGateRule): the site's login on that broker on its
    simulation server, the site's ordering switch showing the user ordering now, the user an active administrator, and
    the login up. The switch is read once per look, and only when a due schedule chose a real broker. A user whose
    schedule chose a real broker and who lacks any of these is followed on no account: the user is left out, never
    moved to the mock account, and the reason is logged once per user, day and reason, since the timer looks every
    minute. The timer asks this again right before
    it starts a user's follow, so a user who turned the schedule off or changed its account meanwhile is not followed.
    It reads no account and ranks nothing: whether a user's follow is due is RankingFollowSchedule's answer, on that
    user's own Pipeline.
    """

    def __init__(
        self,
        user_store: IUserStore,
        real_broker: IExecutionProvider | None,
        ordering_switch: IOrderingSwitch,
        market_clock: IMarketClock,
        config: AppConfig,
        logger: ILoggingProvider,
    ) -> None:
        self._user_store = user_store
        self._real_broker = real_broker
        self._ordering_switch = ordering_switch
        self._market_clock = market_clock
        self._features = config.features
        self._time_rule = config.follow_time_rule()
        self._broker_rule = config.follow_broker_rule()
        self._logged: dict[UserId, tuple[date, str]] = {}
        self._logger = logger

    async def execute(self) -> list[User]:
        now, phase = self._market_clock.to_market_datetime(self._market_clock.now()), self._market_clock.trading_phase()
        link = self._real_broker.link() if self._real_broker is not None else None
        due = [
            user
            for user in await self._user_store.users()
            if user.status == UserStatus.ACTIVE and self._time_rule.apply(user.ranking_follow_time, now, phase)
        ]
        ordering = {
            broker: await self._ordering_switch.visibility(broker)
            for broker in sorted({user.ranking_follow_broker for user in due})
            if broker.real
        }
        followers: list[User] = []

        for user in due:
            broker = user.ranking_follow_broker
            shown = {Feature.RANKING, broker.ordering_feature} <= self._features.shown(user.permissions)
            refusal = self._broker_rule.apply(Workflow.RANKING_FOLLOW, broker, link, user, ordering.get(broker, FeatureVisibility.OFF))

            if shown and refusal is None:
                followers.append(user)
                continue

            if not broker.real:
                continue

            why = refusal[1] if refusal is not None else f"this site does not show the user the ranking and ordering on {broker.value}"

            if self._logged.get(user.user_id) != (now.date(), why):
                self._logged[user.user_id] = now.date(), why
                self._logger.info(f"The scheduled ranking follow of user {user.user_id} on {broker.label} does nothing now: {why}.")

        return followers
