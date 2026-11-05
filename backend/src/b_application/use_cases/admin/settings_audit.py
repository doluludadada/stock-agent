from a_domain.model.system.user import User
from a_domain.ports.system.settings_files import ISettingsFiles, SettingsAuditEntry
from a_domain.ports.system.user_store import IUserStore


class SettingsAudit:
    """
    The latest saves and restores of the settings files, newest first, each with the administrator who made it, read
    from the user store by the id the audit keeps; None for a user who no longer exists.
    """

    def __init__(self, settings_files: ISettingsFiles, user_store: IUserStore) -> None:
        self._settings_files = settings_files
        self._user_store = user_store

    async def execute(self, limit: int) -> list[tuple[SettingsAuditEntry, User | None]]:
        entries = await self._settings_files.audit_entries(limit)
        actors = {actor: await self._user_store.find(actor) for actor in {entry.actor for entry in entries}}
        return [(entry, actors[entry.actor]) for entry in entries]
