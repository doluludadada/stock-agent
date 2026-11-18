from datetime import time

from a_domain.model.system.user import User
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.system.market_clock import IMarketClock
from a_domain.ports.system.user_store import IUserStore
from a_domain.rules.trading.follow import FollowAccount
from a_domain.types.enums import ExecutionProvider
from a_domain.types.errors import FollowBrokerNotOffered, FollowTimeNotOffered
from b_application.config.app_config import AppConfig


class RankingFollowChoice:
    """
    A user's choice on My settings of their ranking follow: their follow account (`broker`) and when the site follows
    each new decision of the monthly ranking by itself there, a time of ranking.follow_times, or no time for no
    schedule. A new account must be one the site offers the user as their follow account now (`account`, as
    RankingFollowSchedule answered it), and so must the account of a schedule that is on: FollowBrokerNotOffered
    otherwise. Turning the schedule off needs no account the site offers, so a user who lost theirs can still stop it.
    A time the site does not offer is refused (FollowTimeNotOffered). A refusal saves nothing.
    """

    def __init__(self, user_store: IUserStore, market_clock: IMarketClock, config: AppConfig, logger: ILoggingProvider) -> None:
        self._user_store = user_store
        self._market_clock = market_clock
        self._times = config.ranking.follow_times
        self._logger = logger

    async def execute(self, user: User, follow_time: time | None, broker: ExecutionProvider, account: FollowAccount) -> User:
        """The user with the choice saved."""
        if (follow_time is not None or broker != account.broker) and broker not in account.brokers:
            offered = ", ".join(offer.label for offer in account.brokers) or "no account"
            raise FollowBrokerNotOffered(f"This site offers you {offered} as your follow account now, not {broker.label}.")

        if follow_time is not None and follow_time not in self._times:
            offered = ", ".join(f"{offer:%H:%M}" for offer in self._times)
            raise FollowTimeNotOffered(f"This site follows the ranking at one of: {offered}.")

        await self._user_store.save_ranking_follow(user.user_id, follow_time, broker, self._market_clock.now())
        user.ranking_follow_time, user.ranking_follow_broker = follow_time, broker
        chosen = f"{follow_time:%H:%M}" if follow_time else "off"
        self._logger.info(f"User {user.user_id} follows the ranking on {broker.label}, on schedule: {chosen}.")

        return user
