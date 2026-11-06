from datetime import datetime

from pydantic import ConfigDict, computed_field
from pydantic.dataclasses import dataclass

from a_domain.types.enums import AiProvider, Permission, Role, UserStatus
from a_domain.types.ids import SessionToken, UserId
from a_domain.types.values import EmailAddress, Username


@dataclass(config=ConfigDict(validate_assignment=True), kw_only=True)
class User:
    """
    A person who signs in, and the owner of their own mock account, watchlist, records and strategies. It holds no
    credential: the user store keeps the password hash and the encrypted username and email, and hands back this model
    with both decrypted, so the Web answers with it.
    """

    user_id: UserId
    username: Username
    email: EmailAddress
    role: Role
    status: UserStatus = UserStatus.ACTIVE
    created_at: datetime
    ai_model: AiProvider | None = None
    """
    The AI model the user chose for their own runs on My settings, None for the site's default. A choice the site stopped
    offering stays saved, and the user's runs use the site's default until it is offered again.
    """

    @computed_field
    @property
    def permissions(self) -> frozenset[Permission]:
        """What the user's role allows beyond their own data: the web app shows the administration pages from it."""
        return self.role.permissions


@dataclass(frozen=True, kw_only=True)
class UserSession:
    """One browser's sign-in: the token its cookie carries and when it stops working. Fixed lifetime, no sliding renewal."""

    token: SessionToken
    user_id: UserId
    created_at: datetime
    expires_at: datetime
