from collections.abc import Sequence

from a_domain.ports.system.settings_files import ISettingsFiles, SettingChange, SettingsForm
from a_domain.types.enums import SettingsFile
from b_application.config.settings_loader import settings_schema, with_changes


class SettingsFormEditor:
    """
    The settings form, a second editor of the administrator's text of appsetting.yaml: the form's changes written into
    the text in place, the settings the text then sets, and what each setting accepts. It writes no file: the page
    checks and saves the text it answers like any text the administrator types.
    """

    def __init__(self, settings_files: ISettingsFiles) -> None:
        self._settings_files = settings_files

    def execute(self, text: str, changes: Sequence[SettingChange]) -> SettingsForm:
        edited = with_changes(SettingsFile.APPSETTING, text, changes)
        return SettingsForm(text=edited, values=self._settings_files.leaves(SettingsFile.APPSETTING, edited), schema=settings_schema())
