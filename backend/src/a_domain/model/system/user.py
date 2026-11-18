from datetime import datetime, time

from pydantic import ConfigDict, computed_field
from pydantic.dataclasses import dataclass

from a_domain.types.enums import AiProvider, ExecutionProvider, Permission, Role, UserStatus
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
    ranking_follow_time: time | None = None
    """
    The time of day in Taipei from which the site follows each new decision of the monthly ranking by itself, on the
    first session after it, into the account `ranking_follow_broker` names. None: only the user's own click follows.
    """
    ranking_follow_broker: ExecutionProvider = ExecutionProvider.MOCK
    """
    The user's follow account, chosen on My settings: the one account their ranking follow orders on, by the ranking
    page's button and by their schedule alike. Their mock account, or SinoPac, where a ranking follow orders on the
    simulation server only. While the site does not offer it to the user (FollowAccountRule), a follow there is
    refused and the schedule does not follow; neither ever moves to another account.
    """
    has_password: bool = True
    """
    Whether a password signs the user in. False for an account that signs in with Google only: it has no password to
    sign in to the CLI with or to re-enter for a settings save, until `just reset-password` or an administrator sets one.
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


@dataclass(frozen=True, kw_only=True)
class GoogleConfirmation:
    """
    The fresh Google authentication that confirms one settings save of an administrator without a password: the id the
    web app made for the save, and the administrator's session that started the authentication, the only session whose
    save it confirms.
    """

    confirmation_id: str
    session: SessionToken


@dataclass(frozen=True, kw_only=True)
class SignInFlow:
    """
    One sign-in a browser started at the identity provider: what the provider must send back (`state`), what its ID
    token must carry (`nonce`), and the PKCE verifier of the code. The browser's flow cookie carries it between the
    start and the return, until `expires_at`, so only the browser that started a flow can finish it.
    """

    state: str
    nonce: str
    code_verifier: str
    started_at: datetime
    expires_at: datetime
    confirmation: GoogleConfirmation | None = None
    """The settings save this flow confirms, and for which session; None for a sign-in."""
