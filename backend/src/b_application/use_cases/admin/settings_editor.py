from collections.abc import Sequence

from a_domain.ports.system.settings_files import ISettingsFiles, SettingChange, SettingsEdit
from a_domain.ports.trading.users_orders import IUsersOrders
from a_domain.types.enums import ExecutionProvider, SettingsFile
from b_application.config.settings_loader import InvalidSettingsError, with_changes


class SettingsEditor:
    """
    Proposes the settings form's changes: each one written into the text of its settings file as it is on disk, and the
    files they change checked together, with the other as it is on disk, by the checks startup runs against the
    settings this process runs on (ISettingsFiles.check), and for a lockout of the editor the administrator reached at
    `host`, and for a switch of SinoPac's server the SinoPac orders of every user that await settlement, counted
    (`users_orders`). InvalidSettingsError with every problem when the app would refuse the new texts;
    SettingsEditError for a change the form cannot write. It writes nothing, and proposes no edit when nothing changes.
    """

    def __init__(self, settings_files: ISettingsFiles, users_orders: IUsersOrders) -> None:
        self._settings_files = settings_files
        self._users_orders = users_orders

    async def execute(self, changes: Sequence[SettingChange], host: str) -> list[SettingsEdit]:
        texts = {file: (await self._settings_files.read(file)).text for file in SettingsFile}
        edits = with_changes(texts, changes)
        candidates = {edit.file: edit.text for edit in edits}

        if not candidates:
            return edits

        unsettled = await self._users_orders.awaiting_settlement(ExecutionProvider.SHIOAJI)

        if problems := self._settings_files.check(candidates, host, unsettled):
            raise InvalidSettingsError(list(problems))

        return edits
