from a_domain.model.system.user import User
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.system.market_clock import IMarketClock
from a_domain.ports.system.user_store import IUserStore
from a_domain.types.enums import Role
from a_domain.types.errors import AlreadySetUpError
from a_domain.types.ids import UserId
from a_domain.types.values import EmailAddress, NewPassword, Username


class FirstAdministratorSetup:
    """
    Creates the first administrator, once per installation, under the id the single-owner versions stored their data
    under, so that data is the administrator's from now on. Two setups at once both name that id, and one fails.
    """

    def __init__(self, user_store: IUserStore, market_clock: IMarketClock, legacy_owner_id: UserId, logger: ILoggingProvider) -> None:
        self._user_store = user_store
        self._market_clock = market_clock
        self._legacy_owner_id = legacy_owner_id
        self._logger = logger

    async def execute(self, username: Username, email: EmailAddress, password: NewPassword) -> User:
        if await self._user_store.user_count() > 0:
            raise AlreadySetUpError("The administrator is set up already. Sign in instead.")

        user = User(
            user_id=self._legacy_owner_id, username=username, email=email, role=Role.ADMINISTRATOR, created_at=self._market_clock.now()
        )
        await self._user_store.create(user, password)
        self._logger.info(f"First administrator set up: {user.user_id}.")

        return user
