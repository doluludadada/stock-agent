import re
from datetime import datetime, timedelta
from secrets import compare_digest

from pydantic.dataclasses import dataclass

from a_domain.model.system.user import SignInFlow, User
from a_domain.types.enums import GoogleRefusal, Permission, Role, UserStatus
from a_domain.types.ids import UserId
from a_domain.types.values import EmailAddress, SignInName, Username


@dataclass(frozen=True, kw_only=True)
class IdTokenClaims:
    """What an ID token says, as the identity provider's token endpoint handed it to the app. Nothing here is checked yet."""

    issuer: str
    audiences: tuple[str, ...]
    nonce: str
    email: str
    email_verified: bool
    expires_at: datetime
    authenticated_at: datetime | None
    """When the person last proved who they are to the provider (auth_time), when the token says."""


@dataclass(frozen=True)
class FlowReturnRule:
    """
    Whether a return from the identity provider belongs to a flow this browser started: the site offers the sign-in,
    the browser still carries a flow that has not expired, the provider sent that flow's state back, and it sent a
    code, not an error.
    """

    offered: bool

    def apply(self, flow: SignInFlow | None, state: str | None, has_code: bool, now: datetime) -> GoogleRefusal | None:
        if not self.offered:
            return GoogleRefusal.NOT_OFFERED

        if flow is None or flow.expires_at <= now:
            return GoogleRefusal.FLOW_MISSING

        if state is None or not compare_digest(state.encode(), flow.state.encode()):
            return GoogleRefusal.STATE_MISMATCH

        return None if has_code else GoogleRefusal.CANCELLED


@dataclass(frozen=True)
class IdTokenRule:
    """
    Whether an ID token is this app's own answer to the sign-in the browser started: from the issuer, for this client
    alone, unexpired, carrying the nonce of the flow and an email the issuer verified. A settings confirmation also
    needs an authentication no older than `fresh_authentication`, so a Google session left open confirms nothing.
    """

    issuers: frozenset[str]
    client_id: str
    clock_skew: timedelta
    fresh_authentication: timedelta

    def apply(self, claims: IdTokenClaims, nonce: str, confirmation: bool, now: datetime) -> GoogleRefusal | None:
        if claims.issuer not in self.issuers or claims.audiences != (self.client_id,):
            return GoogleRefusal.TOKEN_REFUSED

        if claims.expires_at + self.clock_skew <= now or not compare_digest(claims.nonce.encode(), nonce.encode()):
            return GoogleRefusal.TOKEN_REFUSED

        if not claims.email_verified:
            return GoogleRefusal.EMAIL_UNVERIFIED

        if not confirmation:
            return None

        if claims.authenticated_at is None or now - claims.authenticated_at > self.fresh_authentication + self.clock_skew:
            return GoogleRefusal.STALE_AUTHENTICATION

        return None


@dataclass(frozen=True)
class GoogleAdmission:
    """What a sign-in with Google gives a verified email: its account's role, and whether an account it finds keeps its password."""

    role: Role
    keeps_password: bool


@dataclass(frozen=True)
class GoogleAccessRule:
    """
    Who may sign in with Google, by the email Google verified, compared as sign-in compares names and never by domain.
    An administrator email is an administrator, on an installation with no user yet too. Any other email needs an
    administrator to exist: an allowed email is a user, and an email on neither list only while registration is open.
    A deactivated account stays refused.

    The app never verified the email of an account someone registered, so the password chosen with it proves nothing
    about the address. Only an account that already manages the users keeps its password; any other account the email
    finds loses it, with its sessions, so nobody who registered someone else's address shares the account afterwards.
    """

    administrator_emails: frozenset[SignInName]
    allowed_emails: frozenset[SignInName]
    registration_open: bool

    def apply(self, email: SignInName, existing: User | None, user_count: int) -> GoogleAdmission | GoogleRefusal:
        if existing is not None and existing.status != UserStatus.ACTIVE:
            return GoogleRefusal.DEACTIVATED

        trusted = existing is not None and Permission.MANAGE_USERS in existing.permissions

        if email in self.administrator_emails:
            return GoogleAdmission(role=Role.ADMINISTRATOR, keeps_password=trusted)

        if user_count == 0 or not (email in self.allowed_emails or self.registration_open):
            return GoogleRefusal.NOT_ALLOWED

        return GoogleAdmission(role=existing.role if existing is not None else Role.USER, keeps_password=trusted)


@dataclass(frozen=True)
class GoogleUsernameRule:
    """
    The username of an account a sign-in with Google creates: the email's part before the @, without what a username
    may not hold. A name too short, or one someone took (`taken`), ends in the start of the new user's id instead.
    """

    def apply(self, email: EmailAddress, user_id: UserId, taken: bool) -> Username:
        name = re.sub(r"[^A-Za-z0-9._-]", "", email.split("@")[0]).lstrip("._-")[:32]

        if len(name) >= 3 and not taken:
            return name

        return f"{name[:23] or 'user'}-{user_id[:8]}"
