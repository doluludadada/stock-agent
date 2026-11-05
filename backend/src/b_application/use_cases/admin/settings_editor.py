from a_domain.ports.system.settings_files import ISettingsFiles, SettingsEdit
from a_domain.rules.system.settings_change import SettingsChangeRule
from a_domain.types.enums import SettingsFile
from a_domain.types.errors import SettingsConflictError, SettingsEditError, SettingsFileMissing
from b_application.config.app_config import AppConfig


class SettingsEditor:
    """
    Proposes a whole new text for one settings file, written by the administrator or a kept backup to put back, against
    the file as it is on disk: its diff, the settings it changes, and why the app would refuse to start with it, by the
    checks startup runs, or would lock the
    administrator out of the editor they reached at `host`. It writes nothing. A file that moved past the revision the
    administrator read is a conflict: read it again.
    """

    def __init__(self, settings_files: ISettingsFiles, config: AppConfig) -> None:
        self._settings_files = settings_files
        self._change_rule = SettingsChangeRule()
        self._environment = config.environment

    async def execute(
        self, file: SettingsFile, expected_revision: str, host: str, text: str | None = None, backup_id: str | None = None
    ) -> SettingsEdit:
        if (text is None) == (backup_id is None):
            raise SettingsEditError("Propose either a text or a backup to restore.")

        current = await self._settings_files.read(file)

        if current.revision != expected_revision:
            raise SettingsConflictError(f"{file.file_name} changed since revision {expected_revision[:12]}; read it again")

        if (proposed := text if backup_id is None else await self._settings_files.backup_text(file, backup_id)) is None:
            raise SettingsFileMissing(f"No backup {backup_id} of {file.file_name} is kept.")

        saved, edited = self._settings_files.leaves(file, current.text), self._settings_files.leaves(file, proposed)
        return SettingsEdit(
            file=file,
            base_revision=current.revision,
            text=proposed,
            revision=self._settings_files.revision_of(proposed),
            changed=self._change_rule.apply(saved, edited),
            diff=tuple(self._settings_files.diff(file, current.text, proposed)),
            problems=self._settings_files.check(file, proposed, self._environment, host),
            restored_backup_id=backup_id,
        )
