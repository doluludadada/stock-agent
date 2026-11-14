from a_domain.model.system.user import User
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.system.market_clock import IMarketClock
from a_domain.ports.system.user_store import IUserStore
from a_domain.rules.system.google_sign_in import GoogleAdmission, GoogleUsernameRule
from a_domain.types.errors import GoogleSignInRefused
from a_domain.types.ids import UserId, new_user_id
from a_domain.types.values import EmailAddress, comparable_name
from b_application.config.app_config import AppConfig


class GoogleAccount:
    """
    The account of an email Google verified, as GoogleAccessRule admits it: the one that has the email, with the role
    and the password the rule leaves it, or a new one without a password. The first account of an installation gets the
    id the single-owner versions stored their data under, as the first-time setup gives it, so two first sign-ins at
    once cannot both create it. A refused email creates nothing.
    """

    def __init__(
        self, user_store: IUserStore, market_clock: IMarketClock, config: AppConfig, legacy_owner_id: UserId, logger: ILoggingProvider
    ) -> None:
        self._user_store = user_store
        self._market_clock = market_clock
        self._access_rule = config.accounts.google_access_rule()
        self._username_rule = GoogleUsernameRule()
        self._legacy_owner_id = legacy_owner_id
        self._logger = logger

    async def execute(self, email: EmailAddress) -> User:
        """Raises GoogleSignInRefused, or UserExistsError when another sign-in created the account meanwhile."""
        existing, user_count = await self._user_store.find_by_name(email), await self._user_store.user_count()
        admission, now = self._access_rule.apply(comparable_name(email), existing, user_count), self._market_clock.now()

        if not isinstance(admission, GoogleAdmission):
            self._logger.warning(
                f"Google sign-in refused for {existing.user_id if existing else 'an email with no account'}: {admission.label}."
            )
            raise GoogleSignInRefused(admission)

        if existing is None:
            user_id = self._legacy_owner_id if user_count == 0 else new_user_id()
            username = self._username_rule.apply(email, user_id, False)
            username = self._username_rule.apply(email, user_id, await self._user_store.find_by_name(username) is not None)
            user = User(user_id=user_id, username=username, email=email, role=admission.role, created_at=now, has_password=False)
            await self._user_store.create(user, None)
            self._logger.info(f"Google sign-in created the {user.role} {user.user_id}.")
            return user

        keeps_password = existing.has_password and admission.keeps_password

        if (existing.role, existing.has_password) != (admission.role, keeps_password):
            existing.role, existing.has_password = admission.role, keeps_password
            await self._user_store.save(existing, now)
            self._logger.info(f"Google sign-in changed {existing.user_id}: role={existing.role}, has_password={keeps_password}.")

        return existing
