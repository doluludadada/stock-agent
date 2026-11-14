from pydantic.dataclasses import dataclass

from a_domain.model.system.user import User
from a_domain.rules.system.google_sign_in import GoogleAccessRule, GoogleAdmission
from a_domain.rules.system.registration import SignInOffer
from a_domain.types.enums import Permission, UserStatus
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
