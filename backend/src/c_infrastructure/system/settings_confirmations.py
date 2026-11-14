from datetime import datetime
from typing import override

from a_domain.model.system.user import GoogleConfirmation
from a_domain.ports.system.settings_confirmations import ISettingsConfirmations


class MemorySettingsConfirmations(ISettingsConfirmations):
    """
    The grants in this process's memory, by confirmation id and session, each with its expiry. Nothing here
    awaits, so a redeem cannot interleave with another: of two saves with one grant, one is confirmed.
    """

    def __init__(self) -> None:
        self._grants: dict[GoogleConfirmation, datetime] = {}

    @override
    async def grant(self, confirmation: GoogleConfirmation, now: datetime, expires_at: datetime) -> None:
        self._grants = {key: expiry for key, expiry in self._grants.items() if expiry > now}
        self._grants[confirmation] = expires_at

    @override
    async def redeem(self, confirmation: GoogleConfirmation, now: datetime) -> bool:
        expires_at = self._grants.pop(confirmation, None)

        return expires_at is not None and expires_at > now
