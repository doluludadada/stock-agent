from collections.abc import Mapping
from typing import Any

from a_domain.ports.system.settings_files import ISettingsFiles, SettingsEdit
from a_domain.types.enums import EditableSetting, SettingsFile
from a_domain.types.errors import SettingsEditError


class SettingsEditor:
    """
    Proposes a new text for one settings file: the current text with allowlisted settings set to new values, or, for a
    restore, to the values a kept backup holds for them. A restore brings back nothing else from the backup, so a
    locked setting changed in the file since stays as it is now. The proposal carries its diff against the file and
    why the app would refuse to start with it, validated exactly as the app loads its settings. It writes nothing.
    """

    def __init__(self, settings_files: ISettingsFiles) -> None:
        self._settings_files = settings_files

    async def execute(
        self, file: SettingsFile, changes: Mapping[EditableSetting, Any] | None = None, backup_id: str | None = None
    ) -> SettingsEdit:
        if changes and any(setting.file != file for setting in changes):
            raise SettingsEditError(f"Every change must be a setting of {file.file_name}")

        current = await self._settings_files.read(file)
        backup = await self._settings_files.backup_text(file, backup_id) if backup_id is not None else None

        if backup_id is not None and backup is None:
            raise SettingsEditError(f"No backup {backup_id} of {file.file_name}")

        paths = [setting.value for setting in EditableSetting if setting.file == file]
        requested = {setting.value: value for setting, value in (changes or {}).items()}
        text = self._settings_files.edited(current.text, requested if backup is None else self._settings_files.values(backup, paths))
        before, after = self._settings_files.values(current.text, paths), self._settings_files.values(text, paths)
        return SettingsEdit(
            file=file,
            base_revision=current.revision,
            text=text,
            revision=self._settings_files.revision_of(text),
            changed=tuple(path for path in paths if before.get(path) != after.get(path)),
            diff=tuple(self._settings_files.diff(file, current.text, text)),
            problems=tuple(self._settings_files.problems(file, text)),
            values=after,
            restored_backup_id=backup_id,
        )
