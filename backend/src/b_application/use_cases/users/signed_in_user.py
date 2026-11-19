from a_domain.model.system.user import User
from a_domain.ports.system.market_clock import IMarketClock
from a_domain.ports.system.user_store import IUserStore
from a_domain.types.enums import UserStatus
from a_domain.types.ids import SessionToken, UserId


class SignedInUser:
    """
    A signed-in user as saved now, while active: with `user_id` the user the CLI signed in, which it reads again before
    each menu option, so a change applies at once; with `session` whose session a cookie holds now. None for an
    unknown or a deactivated user, and for a session that is unknown or expired.
    """

    def __init__(self, user_store: IUserStore, market_clock: IMarketClock) -> None:
        self._user_store = user_store
        self._market_clock = market_clock

    async def execute(self, *, user_id: UserId | None = None, session: SessionToken | None = None) -> User | None:
        if session is not None:
            return await self._user_store.session_user(session, self._market_clock.now())

        user = await self._user_store.find(user_id) if user_id is not None else None

        return user if user is not None and user.status == UserStatus.ACTIVE else None
