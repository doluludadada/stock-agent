from typing import override

from pydantic.dataclasses import dataclass

from a_domain.model.system.user import User
from a_domain.rules.system.google_sign_in import GoogleAccessRule, GoogleAdmission
from a_domain.rules.system.registration import SignInOffer
from a_domain.types.enums import FeatureVisibility, Permission, ServerSwitchRefusalReason, ShioajiCredential, ShioajiServer, UserStatus
from a_domain.types.ids import UserId
from a_domain.types.values import comparable_name


@dataclass(frozen=True)
class EditorAccessRule:
    """
    New settings must still let an administrator into the editor, or nobody could undo them from the Web. A save needs
    the administrator saving: an active user of the new settings' database, allowed to edit the settings. A reload
    from disk needs any user there, unless the running settings have none yet either: first use sets one up. An
    administrator without a password signs in with Google only, so the new settings must still admit their email.
    """

    google_access: GoogleAccessRule | None = None
    """Who the new settings let sign in with Google; None when they do not offer it."""

    def apply(self, candidate: SignInOffer, running: SignInOffer, saving: UserId | None, found: User | None) -> str | None:
        """
        Why the new settings would lock the administrators out, or None. `saving` is the administrator saving, None for
        a reload; `found` is that id as the new settings' database knows it.
        """
        allowed = found is not None and found.status == UserStatus.ACTIVE and Permission.EDIT_SYSTEM_SETTINGS in found.permissions

        if saving is not None and not allowed:
            return "The new settings' database has no active administrator account of yours to sign in with."

        admission = self.google_access.apply(comparable_name(found.email), found, 1) if self.google_access and found else None

        if found is not None and not found.has_password and not isinstance(admission, GoogleAdmission):
            return (
                "Your account has no password and could not sign in with Google under the new settings. Keep "
                "GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET and accounts.public_origin set and your email in "
                "accounts.google_administrator_emails, or set a password first with `just reset-password`."
            )

        if saving is None and candidate.needs_first_administrator and not running.needs_first_administrator:
            return "The new settings' database has no administrator: nobody could sign in to the editor."

        return None


@dataclass(frozen=True)
class ServerSwitchRefusal:
    """
    Why the site's SinoPac login may not be on `server`, with the variables its login reads that are not set, by name
    only, and how many SinoPac orders await settlement.
    """

    reason: ServerSwitchRefusalReason
    server: ShioajiServer
    missing: tuple[ShioajiCredential, ...] = ()
    unsettled: int = 0

    @override
    def __str__(self) -> str:
        """How the settings check words it, at the setting `reason` names."""
        return self.reason.sentence(self.server, self.missing, self.unsettled)


@dataclass(frozen=True)
class ServerSwitchRule:
    """
    Which SinoPac server the site's login may be on, at a start and at a reload or a save that switches it without a
    restart. Only a server the machine's environment logs in to (`servers`), and never the real account while
    registration is open. A switch from the server the process runs on must also turn SinoPac ordering off in the same
    files, so no order reaches the new server until an administrator turns ordering on again there; no SinoPac order may
    await settlement, since the journal does not name the server an order went to and the new server's record would
    settle it; and every variable the new server's login reads must be set. A start, and a save that keeps the server,
    need none of these: a start on production with ordering on is the state a switch and a deploy leave.
    """

    servers: frozenset[ShioajiServer]

    def apply(
        self,
        running: ShioajiServer | None,
        target: ShioajiServer,
        ordering: FeatureVisibility,
        given: frozenset[ShioajiCredential],
        registration_open: bool,
        unsettled: int,
    ) -> ServerSwitchRefusal | None:
        """
        Why the login may not be on `target`, or None. `running` is the server the process logs in to now, None at its
        first start; `ordering` whom features.sinopac_ordering shows ordering to in the new settings; `given` the
        Shioaji variables that are set; `unsettled` how many SinoPac orders of every user await settlement.
        """
        if target not in self.servers:
            return ServerSwitchRefusal(reason=ServerSwitchRefusalReason.ENVIRONMENT, server=target)

        if registration_open and not target.simulation:
            return ServerSwitchRefusal(reason=ServerSwitchRefusalReason.REGISTRATION_OPEN, server=target)

        if running is None or running == target:
            return None

        if ordering.shown_to_anyone:
            return ServerSwitchRefusal(reason=ServerSwitchRefusalReason.ORDERING_ON, server=target)

        if unsettled:
            return ServerSwitchRefusal(reason=ServerSwitchRefusalReason.ORDERS_UNSETTLED, server=target, unsettled=unsettled)

        if missing := tuple(credential for credential in target.credentials if credential not in given):
            return ServerSwitchRefusal(reason=ServerSwitchRefusalReason.CREDENTIALS_MISSING, server=target, missing=missing)

        return None
