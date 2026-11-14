from datetime import timedelta

from a_domain.model.system.user import SignInFlow
from a_domain.ports.system.attempt_log import AttemptKey, IAttemptLog
from a_domain.ports.system.identity_provider import IIdentityProvider
from a_domain.ports.system.market_clock import IMarketClock
from a_domain.types.enums import AttemptLimit, GoogleRefusal
from a_domain.types.errors import GoogleSignInRefused, SignInThrottled
from b_application.config.app_config import AppConfig


class GoogleSignInStart:
    """
    Starts a sign-in with Google, or the fresh authentication that confirms one settings save: a new flow and Google's
    address for it, good for accounts.google_flow_minutes, inside the limit per client address. Refused where the site
    does not offer sign-in with Google.
    """

    def __init__(
        self, identity_provider: IIdentityProvider | None, attempt_log: IAttemptLog, market_clock: IMarketClock, config: AppConfig
    ) -> None:
        self._identity_provider = identity_provider
        self._attempt_log = attempt_log
        self._market_clock = market_clock
        self._limit = config.accounts.google_sign_in_limit()
        self._redirect_uri = config.accounts.google_redirect_uri
        self._lifetime = timedelta(minutes=config.accounts.google_flow_minutes)

    async def execute(self, confirmation: str | None, client: str) -> tuple[SignInFlow, str]:
        """The flow for the browser's flow cookie, and where the browser goes."""
        if self._identity_provider is None:
            raise GoogleSignInRefused(GoogleRefusal.NOT_OFFERED)

        now = self._market_clock.now()

        if retry_at := await self._attempt_log.admit(now, {AttemptKey(limit=AttemptLimit.GOOGLE_SIGN_IN, client=client): self._limit}):
            raise SignInThrottled(retry_at, now)

        return self._identity_provider.start(self._redirect_uri, confirmation, now, now + self._lifetime)
