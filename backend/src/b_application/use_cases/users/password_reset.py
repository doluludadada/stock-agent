from pydantic import SecretStr

from a_domain.model.system.user import User
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.system.market_clock import IMarketClock
from a_domain.ports.system.user_store import IUserStore


class PasswordReset:
    """
    The operator's `just reset-password` for a locked-out administrator: a new password, saved by the same store call
    as the administrator's change of a user, which ends every session of the user. None when no user has the name.
    """

    def __init__(self, user_store: IUserStore, market_clock: IMarketClock, logger: ILoggingProvider) -> None:
        self._user_store = user_store
        self._market_clock = market_clock
        self._logger = logger

    async def execute(self, identifier: str, password: SecretStr) -> User | None:
        user = await self._user_store.find_by_name(identifier)

        if user is None:
            return None

        await self._user_store.save(user, self._market_clock.now(), password)
        self._logger.info(f"Password reset: {user.user_id}.")

        return user
