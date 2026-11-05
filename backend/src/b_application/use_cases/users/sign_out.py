from a_domain.ports.system.user_store import IUserStore
from a_domain.types.ids import SessionToken


class SignOut:
    """Ends one browser's session. Ending one that does not exist, or ended already, changes nothing."""

    def __init__(self, user_store: IUserStore) -> None:
        self._user_store = user_store

    async def execute(self, token: SessionToken) -> None:
        await self._user_store.close_session(token)
