from a_domain.model.system.user import User
from a_domain.ports.system.market_clock import IMarketClock
from a_domain.ports.system.user_store import IUserStore
from a_domain.rules.trading.follow import FollowTimeRule
from a_domain.types.enums import Feature, UserStatus
from b_application.config.app_config import AppConfig


class ScheduledFollowers:
    """
    The users whose scheduled ranking follow may run now, for the Web API's timer: the active users whose schedule is
    on and whose time has come today, while the market is in the phase this site places an order in (FollowTimeRule),
    and whom the site shows both the ranking and the mock account, as the button's route requires. Outside that phase
    it answers nobody without reading a user, so the timer costs a look at the clock. It reads no account and ranks
    nothing: whether a user's follow is due is RankingFollowSchedule's answer, on that user's own Pipeline.
    """

    def __init__(self, user_store: IUserStore, market_clock: IMarketClock, config: AppConfig) -> None:
        self._user_store = user_store
        self._market_clock = market_clock
        self._features = config.features
        self._pricing = config.audience.order_pricing
        self._time_rule = FollowTimeRule(pricing=config.audience.order_pricing)

    async def execute(self) -> list[User]:
        phase = self._market_clock.trading_phase()

        if phase != self._pricing.trading_phase:
            return []

        now = self._market_clock.to_market_datetime(self._market_clock.now())

        return [
            user
            for user in await self._user_store.users()
            if user.status == UserStatus.ACTIVE
            and self._time_rule.apply(user.ranking_follow_time, now, phase)
            and {Feature.RANKING, Feature.MOCK_ACCOUNT} <= self._features.shown(user.permissions)
        ]
