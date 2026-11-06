from datetime import datetime
from typing import Protocol

from pydantic import SecretStr

from a_domain.model.system.user import User, UserSession
from a_domain.types.enums import AiProvider
from a_domain.types.ids import SessionToken, UserId


class IUserStore(Protocol):
    """
    The users and their sessions. The password is stored only as a slow one-way hash, and the username and the email
    only encrypted, each with a keyed index that keeps it unique and findable without regard to case. Every key comes
    from the one accounts key. None of that reaches a caller: the methods take and return User. These tables
    have no owner: they are the directory of owners, not a user's data.
    """

    async def check_key(self) -> None:
        """Startup's check: raises when users exist and the accounts key is not the key they were saved with."""
        ...

    async def user_count(self) -> int: ...

    async def create(self, user: User, password: SecretStr) -> None:
        """
        Saves a new user. Raises UserExistsError naming the taken field, and AlreadySetUpError when user.user_id exists:
        two first-time setups at once both name the first administrator's id, and the primary key lets one win.
        """
        ...

    async def verify_password(self, identifier: str, password: SecretStr) -> User | None:
        """
        The active user whose username or email, in any case, is `identifier`, when `password` matches; else None, in
        about the same time whether or not such a user exists. A hash made with older parameters is replaced.
        """
        ...

    async def find_by_name(self, identifier: str) -> User | None:
        """The user whose username or email, in any case, is `identifier`, whatever the user's status."""
        ...

    async def open_session(self, user_id: UserId, now: datetime, expires_at: datetime) -> UserSession:
        """A new session for the user. Every session expired by `now` is deleted on the way."""
        ...

    async def session_user(self, token: SessionToken, now: datetime) -> User | None:
        """The user of an unexpired session, when that user is still active. Role and status are read now, every call."""
        ...

    async def close_session(self, token: SessionToken) -> None:
        """Ends the session. Ending one that does not exist changes nothing."""
        ...

    async def users(self) -> list[User]:
        """Every user, oldest first."""
        ...

    async def find(self, user_id: UserId) -> User | None: ...

    async def save(self, user: User, now: datetime, password: SecretStr | None = None) -> None:
        """
        Writes the role and the status, and the new password when one is given, in one transaction, changed at `now`.
        A user who is no longer active, or who gets a new password, loses every session in the same transaction.
        Raises LastAdministratorError, writing nothing, when the save would leave no active administrator: the active
        administrators are locked first, so two administrators demoting each other at once cannot both succeed.
        """
        ...

    async def save_ai_model(self, user_id: UserId, ai_model: AiProvider | None, now: datetime) -> None:
        """
        Writes only the user's choice of AI model, None for the site's default, changed at `now`. It and save() write
        different columns, so neither undoes the other: a user's choice made while an administrator changes their role
        keeps both.
        """
        ...
