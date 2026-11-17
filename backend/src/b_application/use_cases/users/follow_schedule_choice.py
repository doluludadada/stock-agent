from collections.abc import Sequence
from datetime import time

from a_domain.model.system.user import User
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.system.market_clock import IMarketClock
from a_domain.ports.system.user_store import IUserStore
from a_domain.types.enums import ExecutionProvider
from a_domain.types.errors import FeatureHidden, FollowBrokerNotOffered, FollowTimeNotOffered
from b_application.config.app_config import AppConfig


class FollowScheduleChoice:
    """
    A user's choice on My settings of when the site follows each new decision of the monthly ranking by itself, and
    into which account: a time of ranking.follow_times and one of `brokers`, the accounts the site lets the user's
    ranking follow order on now (FollowSchedule.brokers), or no time for no schedule. Setting a time needs the site to
    show the user ordering on the account (FeatureHidden otherwise); turning the schedule off does not, so a user the
    site hid the account from can still stop a schedule. A time the site does not offer (FollowTimeNotOffered) or an
    account it does not offer the user now (FollowBrokerNotOffered) is refused. A refusal saves nothing. The choice is
    the user's alone.
    """

    def __init__(self, user_store: IUserStore, market_clock: IMarketClock, config: AppConfig, logger: ILoggingProvider) -> None:
        self._user_store = user_store
        self._market_clock = market_clock
        self._times = config.ranking.follow_times
        self._ordering = config.features.ordering()
        self._logger = logger

    async def execute(
        self, user: User, follow_time: time | None, broker: ExecutionProvider, brokers: Sequence[ExecutionProvider]
    ) -> User:
        """The user with the choice saved."""
        if follow_time is not None and not self._ordering[broker].shown_to(user.permissions):
            raise FeatureHidden(f"This site does not show you ordering on {broker.label}, which this schedule would order on.")

        if follow_time is not None and follow_time not in self._times:
            offered = ", ".join(f"{offer:%H:%M}" for offer in self._times)
            raise FollowTimeNotOffered(f"This site follows the ranking at one of: {offered}.")

        if follow_time is not None and broker not in brokers:
            offered = ", ".join(offer.label for offer in brokers)
            raise FollowBrokerNotOffered(f"This site lets your ranking follow order on {offered} only, not on {broker.label}.")

        await self._user_store.save_ranking_follow_schedule(user.user_id, follow_time, broker, self._market_clock.now())
        user.ranking_follow_time, user.ranking_follow_broker = follow_time, broker
        chosen = f"{follow_time:%H:%M} on {broker.label}" if follow_time else "off"
        self._logger.info(f"User {user.user_id} scheduled the ranking follow: {chosen}.")

        return user
