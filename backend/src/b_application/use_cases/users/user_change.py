from a_domain.model.system.user import User
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.system.market_clock import IMarketClock
from a_domain.ports.system.user_store import IUserStore
from a_domain.types.enums import Role, UserStatus
from a_domain.types.ids import UserId
from a_domain.types.values import NewPassword


class UserChange:
    """
    The administrator's change of one user: the role, the status, a new password, saved in one transaction. The store
    keeps one active administrator at least (LastAdministratorError, nothing saved). A deactivation or a new password
    ends every session of the user; a run of theirs already running finishes. None when no such user exists.
    """

    def __init__(self, user_store: IUserStore, market_clock: IMarketClock, logger: ILoggingProvider) -> None:
        self._user_store = user_store
        self._market_clock = market_clock
        self._logger = logger

    async def execute(
        self, user_id: UserId, role: Role | None, status: UserStatus | None, password: NewPassword | None
    ) -> User | None:
        user = await self._user_store.find(user_id)

        if user is None:
            return None

        user.role, user.status = role or user.role, status or user.status
        await self._user_store.save(user, self._market_clock.now(), password)

        self._logger.info(f"User {user_id} changed: role={user.role}, status={user.status}, password {'set' if password else 'kept'}.")

        return user
