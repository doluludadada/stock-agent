from collections.abc import Mapping
from typing import Any

from pydantic.dataclasses import dataclass

from a_domain.model.system.user import User
from a_domain.rules.system.registration import SignInOffer
from a_domain.types.enums import Permission, UserStatus
from a_domain.types.ids import UserId


@dataclass(frozen=True)
class SettingsChangeRule:
    """
    Which settings a proposed file changes: `saved` and `proposed` are the file's settings by dotted path, None for a
    text that does not parse. A proposal that does not parse names no setting: its parse problem says why.
    """

    def apply(self, saved: Mapping[str, Any] | None, proposed: Mapping[str, Any] | None) -> tuple[str, ...]:
        """Every dotted path whose value the text changes, a removed or an added one included: what the audit records."""
        if proposed is None:
            return ()

        saved = saved or {}
        return tuple(
            sorted(
                path
                for path in saved.keys() | proposed.keys()
                if path not in saved or path not in proposed or saved[path] != proposed[path]
            )
        )


@dataclass(frozen=True)
class EditorAccessRule:
    """
    New settings must still let an administrator into the editor, or nobody could undo them from the Web. A save needs
    the administrator saving: an active user of the new settings' database, allowed to edit the settings. A reload
    from disk needs any user there, unless the running settings have none yet either: first use sets one up.
    """

    def apply(self, candidate: SignInOffer, running: SignInOffer, saving: UserId | None, found: User | None) -> str | None:
        """
        Why the new settings would lock the administrators out, or None. `saving` is the administrator saving, None for
        a reload; `found` is that id as the new settings' database knows it.
        """
        allowed = found is not None and found.status == UserStatus.ACTIVE and Permission.EDIT_SYSTEM_SETTINGS in found.permissions

        if saving is not None and not allowed:
            return "The new settings' database has no active administrator account of yours to sign in with."

        if saving is None and candidate.needs_first_administrator and not running.needs_first_administrator:
            return "The new settings' database has no administrator: nobody could sign in to the editor."

        return None
