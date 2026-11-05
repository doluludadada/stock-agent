from dataclasses import replace

from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.system.market_clock import IMarketClock
from a_domain.ports.system.settings_files import ISettingsFiles, SettingsAuditEntry, SettingsEdit
from a_domain.types.enums import SettingsAction
from a_domain.types.ids import UserId


class SettingsSave:
    """
    Writes a proposed settings file the app would start with, while the file is still at the revision it was proposed
    against (SettingsConflictError otherwise, nothing written): the old text backed up, the new one put in place
    atomically, and an audit entry naming the administrator by id and the setting paths it changed.
    """

    def __init__(self, settings_files: ISettingsFiles, market_clock: IMarketClock, logger: ILoggingProvider) -> None:
        self._settings_files = settings_files
        self._market_clock = market_clock
        self._logger = logger

    async def execute(self, edit: SettingsEdit, actor: UserId) -> SettingsEdit:
        action = SettingsAction.RESTORE if edit.restored_backup_id is not None else SettingsAction.SAVE
        entry = SettingsAuditEntry(
            recorded_at=self._market_clock.now(),
            file=edit.file,
            action=action,
            actor=actor,
            from_revision=edit.base_revision,
            to_revision=edit.revision,
            settings=edit.changed,
        )
        saved = await self._settings_files.replace(edit.file, edit.text, edit.base_revision, entry)
        self._logger.info(f"Settings {action.value} of {edit.file.file_name} by {actor}: {len(edit.changed)} settings changed.")

        return replace(edit, saved=saved)
