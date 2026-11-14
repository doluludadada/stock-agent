from a_domain.ports.system.settings_files import ISettingsFiles, SettingField
from a_domain.types.enums import SettingsFile
from b_application.config.settings_loader import parsed_document, settings_fields


class SettingsReader:
    """
    The administrator's settings form: every setting of appsetting.yaml and every AI prompt of instructions.yaml, with
    the value the file on disk sets, else its default, and the built-in strategies on disk as the options of the
    settings that name one. InvalidSettingsError at the parser's mark for a file that does not
    parse.
    """

    def __init__(self, settings_files: ISettingsFiles) -> None:
        self._settings_files = settings_files

    async def execute(self) -> list[SettingField]:
        documents = {file: parsed_document(file, (await self._settings_files.read(file)).text) for file in SettingsFile}
        return settings_fields(documents, self._settings_files.built_in_strategy_ids())
