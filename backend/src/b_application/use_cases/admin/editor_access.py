from a_domain.ports.system.settings_files import SettingsProblem
from a_domain.ports.system.user_store import IUserStore
from a_domain.rules.system.registration import SignInOffer
from a_domain.rules.system.settings_change import EditorAccessRule
from a_domain.types.ids import UserId
from b_application.config.app_config import AppConfig
from b_application.config.settings_loader import InvalidSettingsError


class EditorAccess:
    """
    Refuses settings, before a save or a reload puts them in place, whose database would let no administrator into the
    editor: the one saving, who without a password must still be admitted by Google, or for a reload anyone at all.
    """

    def __init__(self, user_store: IUserStore, config: AppConfig) -> None:
        self._user_store = user_store
        self._rule = EditorAccessRule(google_access=config.accounts.google_access_rule() if config.accounts.google_sign_in else None)

    async def execute(self, candidate: SignInOffer, running: SignInOffer, saving: UserId | None) -> None:
        found = await self._user_store.find(saving) if saving is not None else None

        if (refusal := self._rule.apply(candidate, running, saving, found)) is not None:
            raise InvalidSettingsError([SettingsProblem(message=refusal)])
