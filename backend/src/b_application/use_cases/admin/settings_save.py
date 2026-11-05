from dataclasses import replace

from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.system.market_clock import IMarketClock
from a_domain.ports.system.settings_files import ISettingsFiles, SettingsAuditEntry, SettingsEdit
from a_domain.types.enums import SettingsAction
from a_domain.types.errors import SettingsConflictError


class SettingsSave:
    """
    Writes a proposed settings file when it has no problems and the file is still at the revision the administrator
    read, with a backup of the old text and an audit entry of the setting paths it changed. It raises
    SettingsConflictError, writing nothing, when the file changed since. The running process keeps the settings it
    loaded; the file applies at the next start.
    """

    def __init__(self, settings_files: ISettingsFiles, market_clock: IMarketClock, logger: ILoggingProvider) -> None:
        self._settings_files = settings_files
        self._market_clock = market_clock
        self._logger = logger

    async def execute(self, edit: SettingsEdit, expected_revision: str) -> SettingsEdit:
        if edit.problems:
            return edit

        if edit.base_revision != expected_revision:
            raise SettingsConflictError(f"{edit.file.file_name} changed since revision {expected_revision[:12]}; read it again")

        action = SettingsAction.RESTORE if edit.restored_backup_id is not None else SettingsAction.SAVE
        entry = SettingsAuditEntry(
            recorded_at=self._market_clock.now(),
            file=edit.file,
            action=action,
            actor="admin",
            from_revision=edit.base_revision,
            to_revision=edit.revision,
            settings=edit.changed,
        )
        saved = await self._settings_files.replace(edit.file, edit.text, expected_revision, entry)
        self._logger.info(
            f"Settings {action.value} of {edit.file.file_name}: {len(edit.changed)} settings; applies at the next start."
        )

        return replace(edit, saved=saved)
