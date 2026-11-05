from pydantic import SecretStr

from a_domain.model.system.user import User
from a_domain.ports.system.attempt_log import AttemptKey, IAttemptLog
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.system.market_clock import IMarketClock
from a_domain.ports.system.user_store import IUserStore
from a_domain.types.enums import AttemptLimit
from a_domain.types.errors import SignInRefused, SignInThrottled
from b_application.config.app_config import AppConfig


class SignInAttempt:
    """
    Checks a sign-in name (a username or an email) and a password, inside the attempt limits: failures are counted per
    sign-in name and client address and per client address, so guesses from one place never lock the user out from
    another. The CLI and the Web share it. Each attempt is counted before its password is checked, so sign-ins that run
    at once cannot pass the limit together; a refused attempt is taken back, and a success clears the name's failures
    from that client.
    """

    def __init__(
        self, user_store: IUserStore, attempt_log: IAttemptLog, market_clock: IMarketClock, config: AppConfig, logger: ILoggingProvider
    ) -> None:
        self._user_store = user_store
        self._attempt_log = attempt_log
        self._market_clock = market_clock
        self._name_limit = config.accounts.sign_in_name_limit()
        self._client_limit = config.accounts.sign_in_client_limit()
        self._logger = logger

    async def execute(self, identifier: str, password: SecretStr, client: str) -> User:
        now = self._market_clock.now()
        name_key = AttemptKey(limit=AttemptLimit.SIGN_IN_NAME, client=client, name=identifier)
        client_key = AttemptKey(limit=AttemptLimit.SIGN_IN_CLIENT, client=client)
        if retry_at := await self._attempt_log.admit(now, {name_key: self._name_limit, client_key: self._client_limit}):
            raise SignInThrottled(retry_at, now)

        user = await self._user_store.verify_password(identifier, password)

        if user is None:
            self._logger.warning(f"Sign-in refused from {client}.")
            raise SignInRefused("Wrong username, email or password.")

        await self._attempt_log.clear(name_key)
        await self._attempt_log.forget(client_key, now)

        return user
