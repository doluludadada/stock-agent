from datetime import time

from a_domain.model.system.user import User
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.system.market_clock import IMarketClock
from a_domain.ports.system.user_store import IUserStore
from a_domain.types.enums import Feature
from a_domain.types.errors import FeatureHidden, FollowTimeNotOffered
from b_application.config.app_config import AppConfig


class FollowTimeChoice:
    """
    A user's choice on My settings of when the site follows each new decision of the monthly ranking into their mock
    account by itself: one of ranking.follow_times, or None for no schedule. Setting a time needs the site to show
    the user the mock account (FeatureHidden otherwise); turning the schedule off does not, so a user the site hid the
    account from can still stop a schedule. A time the site does not offer is refused (FollowTimeNotOffered). A
    refusal saves nothing. The choice is the user's alone and names no broker: a scheduled follow orders on the mock
    account, like the button.
    """

    def __init__(self, user_store: IUserStore, market_clock: IMarketClock, config: AppConfig, logger: ILoggingProvider) -> None:
        self._user_store = user_store
        self._market_clock = market_clock
        self._times = config.ranking.follow_times
        self._mock_account = config.features.visibility(Feature.MOCK_ACCOUNT)
        self._logger = logger

    async def execute(self, user: User, follow_time: time | None) -> User:
        """The user with the choice saved."""
        if follow_time is not None and not self._mock_account.shown_to(user.permissions):
            raise FeatureHidden("This site does not show you the mock account, which a scheduled follow orders on.")

        if follow_time is not None and follow_time not in self._times:
            offered = ", ".join(f"{offer:%H:%M}" for offer in self._times)
            raise FollowTimeNotOffered(f"This site follows the ranking at one of: {offered}.")

        await self._user_store.save_ranking_follow_time(user.user_id, follow_time, self._market_clock.now())
        user.ranking_follow_time = follow_time
        self._logger.info(f"User {user.user_id} scheduled the ranking follow: {f'{follow_time:%H:%M}' if follow_time else 'off'}.")

        return user
