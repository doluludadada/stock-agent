from collections.abc import Sequence

from a_domain.ports.system.settings_files import ISettingsFiles, SettingChange, SettingsEdit
from a_domain.ports.trading.users_orders import IUsersOrders
from a_domain.types.enums import ExecutionProvider, SettingsFile
from b_application.config.app_config import AppConfig
from b_application.config.settings_loader import startup_settings, validate_editor_reachable, with_changes


class SettingsEditor:
    """
    Proposes the settings form's changes, each written into its file's text as it is on disk, and checks the new texts
    as a reload would against `config`, the settings this process runs on, and for a lockout of the administrator who
    reached the editor at `host`. InvalidSettingsError with every problem when the app would refuse them;
    SettingsEditError for a change the form cannot write. It writes nothing, and proposes no edit when nothing changes.
    """

    def __init__(self, settings_files: ISettingsFiles, users_orders: IUsersOrders, config: AppConfig) -> None:
        self._settings_files = settings_files
        self._users_orders = users_orders
        self._config = config

    async def execute(self, changes: Sequence[SettingChange], host: str) -> list[SettingsEdit]:
        texts = {file: (await self._settings_files.read(file)).text for file in SettingsFile}
        edits = with_changes(texts, changes)

        if not edits:
            return edits

        candidates = {**texts, **{edit.file: edit.text for edit in edits}}
        unsettled = await self._users_orders.awaiting_settlement(ExecutionProvider.SHIOAJI)
        saved = startup_settings(self._config.project_root, candidates, self._config, unsettled=unsettled)
        validate_editor_reachable(saved, candidates, host)
        return edits
