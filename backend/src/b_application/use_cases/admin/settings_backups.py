from a_domain.ports.system.settings_files import ISettingsFiles, SettingsBackup
from a_domain.types.enums import SettingsFile


class SettingsBackups:
    """Lists the kept backups of one settings file, newest first, for the administrator to preview or put back."""

    def __init__(self, settings_files: ISettingsFiles) -> None:
        self._settings_files = settings_files

    async def execute(self, file: SettingsFile) -> list[SettingsBackup]:
        return await self._settings_files.backups(file)
