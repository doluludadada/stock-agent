from datetime import datetime
from typing import Protocol

from a_domain.types.ids import UserId


class ISettingsConfirmations(Protocol):
    """
    The fresh Google authentications that each confirm one settings save of an administrator without a password. Kept
    by this process only, like the attempt log: a restart forgets them, and the administrator confirms again.
    """

    async def grant(self, administrator: UserId, confirmation: str, now: datetime, expires_at: datetime) -> None:
        """
        The administrator authenticated again for the save the web app named `confirmation`. Grants expired by `now`
        are forgotten on the way.
        """
        ...

    async def redeem(self, administrator: UserId, confirmation: str, now: datetime) -> bool:
        """Whether that grant exists and has not expired. It is used up either way: one authentication confirms one save."""
        ...
