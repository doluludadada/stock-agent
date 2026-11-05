from pydantic import SecretStr

from a_domain.model.system.user import User
from a_domain.ports.system.attempt_log import AttemptKey, IAttemptLog
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.system.market_clock import IMarketClock
from a_domain.ports.system.settings_files import SettingsEdit
from a_domain.ports.system.user_store import IUserStore
from a_domain.types.enums import AttemptLimit
from a_domain.types.errors import PasswordRefused, PasswordRequired, SignInThrottled
from b_application.config.app_config import AppConfig
from b_application.config.settings_loader import InvalidSettingsError


class SettingsConfirmation:
    """
    The administrator confirms a save or a restore of a settings file the app would start with, by their own password
    inside its attempt limit, so a stolen session alone changes no setting. A text with problems is refused first
    (InvalidSettingsError with them, never saved). Each try is counted before the password is checked, per
    administrator and client address under its own limit, so tries made at once cannot pass the limit together, a stolen
    session cannot guess faster than the sign-in allows, and guessing here never locks the sign-in out.
    """

    def __init__(
        self, user_store: IUserStore, attempt_log: IAttemptLog, market_clock: IMarketClock, config: AppConfig, logger: ILoggingProvider
    ) -> None:
        self._user_store = user_store
        self._attempt_log = attempt_log
        self._market_clock = market_clock
        self._limit = config.accounts.settings_password_limit()
        self._logger = logger

    async def execute(self, administrator: User, edit: SettingsEdit, password: SecretStr | None, client: str) -> None:
        if edit.problems:
            raise InvalidSettingsError(list(edit.problems))

        if password is None:
            raise PasswordRequired("Re-enter your password to save the settings. Nothing was saved.")

        now = self._market_clock.now()
        key = AttemptKey(limit=AttemptLimit.SETTINGS_PASSWORD, client=client, name=administrator.username)

        if retry_at := await self._attempt_log.admit(now, {key: self._limit}):
            raise SignInThrottled(retry_at, now)

        confirmed = await self._user_store.verify_password(administrator.username, password)

        if confirmed is None or confirmed.user_id != administrator.user_id:
            self._logger.warning(f"Settings password refused for {administrator.user_id} from {client}.")
            raise PasswordRefused("The password is wrong. Nothing was saved.")

        await self._attempt_log.clear(key)
