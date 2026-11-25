from a_domain.model.system.user import User
from a_domain.ports.system.user_store import IUserStore
from a_domain.types.enums import UserStatus
from a_domain.types.ids import UserId


class SignedInUser:
    """
    The user the CLI signed in, as saved now, which the CLI reads again before each menu option, so a change applies at
    once. None for an unknown or a deactivated user.
    """

    def __init__(self, user_store: IUserStore) -> None:
        self._user_store = user_store

    async def execute(self, user_id: UserId) -> User | None:
        user = await self._user_store.find(user_id)

        return user if user is not None and user.status == UserStatus.ACTIVE else None
