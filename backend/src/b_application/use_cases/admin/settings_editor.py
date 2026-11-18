from collections.abc import Sequence

from a_domain.ports.system.settings_files import ISettingsFiles, SettingChange, SettingsEdit
from a_domain.types.enums import SettingsFile
from b_application.config.settings_loader import InvalidSettingsError, with_changes


class SettingsEditor:
    """
    Proposes the settings form's changes: each one written into the text of its settings file as it is on disk, and the
    files they change checked together, with the other as it is on disk, by the checks startup runs against the
    settings this process runs on (ISettingsFiles.check), and for a lockout of the editor the administrator reached at
    `host`. InvalidSettingsError with every problem when the app would refuse the new texts;
    SettingsEditError for a change the form cannot write. It writes nothing, and proposes no edit when nothing changes.
    """

    def __init__(self, settings_files: ISettingsFiles) -> None:
        self._settings_files = settings_files

    async def execute(self, changes: Sequence[SettingChange], host: str) -> list[SettingsEdit]:
        texts = {file: (await self._settings_files.read(file)).text for file in SettingsFile}
        edits = with_changes(texts, changes)
        candidates = {edit.file: edit.text for edit in edits}

        if candidates and (problems := self._settings_files.check(candidates, host)):
            raise InvalidSettingsError(list(problems))

        return edits
