from datetime import timedelta

from a_domain.model.system.user import GoogleConfirmation
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.system.market_clock import IMarketClock
from a_domain.ports.system.settings_confirmations import ISettingsConfirmations
from a_domain.ports.system.user_store import IUserStore
from a_domain.types.enums import GoogleRefusal, Permission
from a_domain.types.errors import GoogleSignInRefused
from a_domain.types.values import EmailAddress, comparable_name
from b_application.config.app_config import AppConfig


class SettingsReauthentication:
    """
    An administrator just authenticated at Google again for one settings save: the save the web app named is granted to
    the session that started the authentication, for accounts.google_fresh_authentication_seconds, when that session
    is still an active administrator's and Google authenticated that administrator's own email. Another Google account
    grants nothing, and no other session of the administrator can use the grant.
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

    async def execute(self, email: EmailAddress, confirmation: GoogleConfirmation) -> None:
        now = self._market_clock.now()
        administrator = await self._user_store.session_user(confirmation.session, now)

        if (
            administrator is None
            or Permission.EDIT_SYSTEM_SETTINGS not in administrator.permissions
            or comparable_name(administrator.email) != comparable_name(email)
        ):
            self._logger.warning("Settings confirmation refused: the Google account is not the active administrator's who started it.")
            raise GoogleSignInRefused(GoogleRefusal.NOT_ADMINISTRATOR)

        await self._confirmations.grant(confirmation, now, now + self._lifetime)
        self._logger.info(f"Settings confirmation granted to {administrator.user_id} by a fresh Google authentication.")
