from datetime import timedelta

from a_domain.model.system.user import User, UserSession
from a_domain.ports.system.market_clock import IMarketClock
from a_domain.ports.system.user_store import IUserStore
from b_application.config.app_config import AppConfig


class SessionStart:
    """Opens a session for a user who just signed in, for accounts.session_days. A request never extends it."""

    def __init__(self, user_store: IUserStore, market_clock: IMarketClock, config: AppConfig) -> None:
        self._user_store = user_store
        self._market_clock = market_clock
        self._lifetime = timedelta(days=config.accounts.session_days)

    async def execute(self, user: User) -> UserSession:
        now = self._market_clock.now()

        return await self._user_store.open_session(user.user_id, now, now + self._lifetime)
