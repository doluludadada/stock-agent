from a_domain.model.system.user import User
from a_domain.ports.system.market_clock import IMarketClock
from a_domain.ports.system.user_store import IUserStore
from a_domain.types.ids import SessionToken


class SessionUser:
    """Whose session a cookie holds now: None when it is unknown or expired, or its user was deactivated since."""

    def __init__(self, user_store: IUserStore, market_clock: IMarketClock) -> None:
        self._user_store = user_store
        self._market_clock = market_clock

    async def execute(self, token: SessionToken) -> User | None:
        return await self._user_store.session_user(token, self._market_clock.now())
