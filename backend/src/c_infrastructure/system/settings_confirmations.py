from datetime import datetime
from typing import override

from a_domain.ports.system.settings_confirmations import ISettingsConfirmations
from a_domain.types.ids import UserId


class MemorySettingsConfirmations(ISettingsConfirmations):
    """
    The grants in this process's memory, by administrator and confirmation id, each with its expiry. Nothing here
    awaits, so a redeem cannot interleave with another: of two saves with one grant, one is confirmed.
    """

    def __init__(self) -> None:
        self._grants: dict[tuple[UserId, str], datetime] = {}

    @override
    async def grant(self, administrator: UserId, confirmation: str, now: datetime, expires_at: datetime) -> None:
        self._grants = {key: expiry for key, expiry in self._grants.items() if expiry > now}
        self._grants[administrator, confirmation] = expires_at

    @override
    async def redeem(self, administrator: UserId, confirmation: str, now: datetime) -> bool:
        expires_at = self._grants.pop((administrator, confirmation), None)

        return expires_at is not None and expires_at > now
