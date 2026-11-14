from pydantic import SecretStr

from a_domain.model.system.user import SignInFlow
from a_domain.ports.system.attempt_log import AttemptKey, IAttemptLog
from a_domain.ports.system.identity_provider import IIdentityProvider
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.system.market_clock import IMarketClock
from a_domain.types.enums import AttemptLimit, GoogleRefusal
from a_domain.types.errors import GoogleSignInRefused, IdentityProviderError, SignInThrottled
from a_domain.types.values import EmailAddress
from b_application.config.app_config import AppConfig


class GoogleIdentityCheck:
    """
    The browser's return from Google: the flow its cookie carries against the state Google sent back, the code
    exchanged at Google's token endpoint, and the ID token checked. Every return counts toward the limit per client
    address before anything is checked; one that proves a Google identity takes itself and its start back. A refusal
    is logged with its reason and the client address, never with a code, a token or an email.
    """

    def __init__(
        self,
        identity_provider: IIdentityProvider | None,
        attempt_log: IAttemptLog,
        market_clock: IMarketClock,
        config: AppConfig,
        logger: ILoggingProvider,
    ) -> None:
        self._identity_provider = identity_provider
        self._attempt_log = attempt_log
        self._market_clock = market_clock
        self._limit = config.accounts.google_sign_in_limit()
        self._return_rule = config.accounts.flow_return_rule()
        self._id_token_rule = config.accounts.id_token_rule()
        self._redirect_uri = config.accounts.google_redirect_uri
        self._logger = logger

    async def execute(self, flow: SignInFlow | None, state: str | None, code: SecretStr | None, client: str) -> EmailAddress:
        """The email Google verified for the person who finished the flow. Raises GoogleSignInRefused or SignInThrottled."""
        now = self._market_clock.now()
        key = AttemptKey(limit=AttemptLimit.GOOGLE_SIGN_IN, client=client)

        if retry_at := await self._attempt_log.admit(now, {key: self._limit}):
            raise SignInThrottled(retry_at, now)

        refusal = self._return_rule.apply(flow, state, code is not None, now)

        if refusal is not None or flow is None or code is None or self._identity_provider is None:
            self._logger.warning(f"Google sign-in refused from {client}: {(refusal or GoogleRefusal.NOT_OFFERED).label}.")
            raise GoogleSignInRefused(refusal or GoogleRefusal.NOT_OFFERED)

        try:
            claims = await self._identity_provider.redeem(code, flow, self._redirect_uri)
        except IdentityProviderError as error:
            self._logger.warning(f"Google sign-in refused from {client}: {error}")
            raise GoogleSignInRefused(GoogleRefusal.PROVIDER_FAILED) from None

        if (refusal := self._id_token_rule.apply(claims, flow.nonce, flow.confirmation is not None, now)) is not None:
            self._logger.warning(f"Google sign-in refused from {client}: {refusal.label}.")
            raise GoogleSignInRefused(refusal)

        await self._attempt_log.forget(key, now)
        await self._attempt_log.forget(key, flow.started_at)

        return claims.email
