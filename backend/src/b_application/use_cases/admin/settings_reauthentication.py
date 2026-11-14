from datetime import timedelta

from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.system.market_clock import IMarketClock
from a_domain.ports.system.settings_confirmations import ISettingsConfirmations
from a_domain.ports.system.user_store import IUserStore
from a_domain.types.enums import GoogleRefusal, Permission, UserStatus
from a_domain.types.errors import GoogleSignInRefused
from a_domain.types.values import EmailAddress
from b_application.config.app_config import AppConfig


class SettingsReauthentication:
    """
    An administrator just authenticated at Google again for one settings save: the save the web app named is granted to
    the active administrator who has that email, for accounts.google_fresh_authentication_seconds. Another Google
    account grants nothing, whoever is signed in to the app.
    """

    def __init__(
        self,
        user_store: IUserStore,
        confirmations: ISettingsConfirmations,
        market_clock: IMarketClock,
        config: AppConfig,
        logger: ILoggingProvider,
    ) -> None:
        self._user_store = user_store
        self._confirmations = confirmations
        self._market_clock = market_clock
        self._lifetime = timedelta(seconds=config.accounts.google_fresh_authentication_seconds)
        self._logger = logger

    async def execute(self, email: EmailAddress, confirmation: str) -> None:
        administrator = await self._user_store.find_by_name(email)

        if (
            administrator is None
            or administrator.status != UserStatus.ACTIVE
            or Permission.EDIT_SYSTEM_SETTINGS not in administrator.permissions
        ):
            self._logger.warning("Settings confirmation refused: the Google account is no active administrator's.")
            raise GoogleSignInRefused(GoogleRefusal.NOT_ADMINISTRATOR)

        now = self._market_clock.now()
        await self._confirmations.grant(administrator.user_id, confirmation, now, now + self._lifetime)
        self._logger.info(f"Settings confirmation granted to {administrator.user_id} by a fresh Google authentication.")
