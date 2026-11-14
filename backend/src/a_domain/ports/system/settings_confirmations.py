from datetime import datetime
from typing import Protocol

from a_domain.model.system.user import GoogleConfirmation


class ISettingsConfirmations(Protocol):
    """
    The fresh Google authentications that each confirm one settings save of an administrator without a password, from
    the session that started the authentication and no other. Kept by this process only, like the attempt log: a
    restart forgets them, and the administrator confirms again.
    """

    async def grant(self, confirmation: GoogleConfirmation, now: datetime, expires_at: datetime) -> None:
        """
        The administrator of the confirmation's session authenticated again for the save it names. Grants expired by
        `now` are forgotten on the way.
        """
        ...

    async def redeem(self, confirmation: GoogleConfirmation, now: datetime) -> bool:
        """Whether that grant exists and has not expired. It is used up either way: one authentication confirms one save."""
        ...
