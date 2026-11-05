from a_domain.model.system.user import User
from a_domain.ports.system.user_store import IUserStore


class UserDirectory:
    """The administrator's list of users, oldest first."""

    def __init__(self, user_store: IUserStore) -> None:
        self._user_store = user_store

    async def execute(self) -> list[User]:
        return await self._user_store.users()
