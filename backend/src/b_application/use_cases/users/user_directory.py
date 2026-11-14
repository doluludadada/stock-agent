from a_domain.model.system.user import User
from a_domain.ports.system.market_clock import IMarketClock
from a_domain.ports.system.user_store import IUserStore
from a_domain.types.enums import UserStatus
from a_domain.types.ids import SessionToken, UserId


class UserDirectory:
    """
    The users as saved now: all of them, oldest first, for the administrator's list; with `user_id` the list that
    holds that user while active, which the CLI reads again before each menu option, so a change applies at once; with
    `session` the list that holds whose session a cookie holds now. Empty for an unknown or a deactivated user, and
    for a session that is unknown or expired.
    """

    def __init__(self, user_store: IUserStore, market_clock: IMarketClock) -> None:
        self._user_store = user_store
        self._market_clock = market_clock

    async def execute(self, *, user_id: UserId | None = None, session: SessionToken | None = None) -> list[User]:
        if session is not None:
            user = await self._user_store.session_user(session, self._market_clock.now())

            return [] if user is None else [user]

        if user_id is not None:
            user = await self._user_store.find(user_id)

            return [user] if user is not None and user.status == UserStatus.ACTIVE else []

        return await self._user_store.users()
