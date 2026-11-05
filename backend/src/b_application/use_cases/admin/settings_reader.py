from a_domain.ports.system.settings_files import ISettingsFiles, SettingsDocument
from a_domain.types.enums import SettingsFile


class SettingsReader:
    """Reads one settings file as it is on disk, for the administrator's editor."""

    def __init__(self, settings_files: ISettingsFiles) -> None:
        self._settings_files = settings_files

    async def execute(self, file: SettingsFile) -> SettingsDocument:
        return await self._settings_files.read(file)
