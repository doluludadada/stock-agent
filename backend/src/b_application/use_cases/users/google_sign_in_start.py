from datetime import timedelta

from a_domain.model.system.user import GoogleConfirmation, SignInFlow
from a_domain.ports.system.attempt_log import AttemptKey, IAttemptLog
from a_domain.ports.system.identity_provider import IIdentityProvider
from a_domain.ports.system.market_clock import IMarketClock
from a_domain.ports.system.user_store import IUserStore
from a_domain.types.enums import AttemptLimit, GoogleRefusal, Permission
from a_domain.types.errors import GoogleSignInRefused, SignInThrottled
from a_domain.types.ids import SessionToken
from b_application.config.app_config import AppConfig


class GoogleSignInStart:
    """
    Starts a sign-in with Google, or the fresh authentication that confirms one settings save: a new flow and Google's
    address for it, good for accounts.google_flow_minutes, inside the limit per client address. Refused where the site
    does not offer sign-in with Google. A confirmation starts only from the session of an active administrator who may
    edit the settings, and its flow carries that session, so nobody else starts one for an id of their choosing.
    """

    def __init__(
        self,
        identity_provider: IIdentityProvider | None,
        attempt_log: IAttemptLog,
        user_store: IUserStore,
        market_clock: IMarketClock,
        config: AppConfig,
    ) -> None:
        self._identity_provider = identity_provider
        self._attempt_log = attempt_log
        self._user_store = user_store
        self._market_clock = market_clock
        self._limit = config.accounts.google_sign_in_limit()
        self._redirect_uri = config.accounts.google_redirect_uri
        self._lifetime = timedelta(minutes=config.accounts.google_flow_minutes)

    async def execute(self, confirmation_id: str | None, session: SessionToken | None, client: str) -> tuple[SignInFlow, str]:
        """
        The flow for the browser's flow cookie, and where the browser goes: a sign-in without a `confirmation_id`, else
        the confirmation of the save it names for `session`, the caller's.
        """
        if self._identity_provider is None:
            raise GoogleSignInRefused(GoogleRefusal.NOT_OFFERED)

        now = self._market_clock.now()
        confirmation = None

        if confirmation_id is not None:
            administrator = await self._user_store.session_user(session, now) if session is not None else None

            if session is None or administrator is None or Permission.EDIT_SYSTEM_SETTINGS not in administrator.permissions:
                raise GoogleSignInRefused(GoogleRefusal.NOT_ADMINISTRATOR)

            confirmation = GoogleConfirmation(confirmation_id=confirmation_id, session=session)

        if retry_at := await self._attempt_log.admit(now, {AttemptKey(limit=AttemptLimit.GOOGLE_SIGN_IN, client=client): self._limit}):
            raise SignInThrottled(retry_at, now)

        return self._identity_provider.start(self._redirect_uri, confirmation, now, now + self._lifetime)
