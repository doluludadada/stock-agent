from a_domain.model.system.user import User
from a_domain.ports.system.attempt_log import AttemptKey, IAttemptLog
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.system.market_clock import IMarketClock
from a_domain.ports.system.user_store import IUserStore
from a_domain.types.enums import AttemptLimit, Role
from a_domain.types.errors import RegistrationClosed, SignInThrottled
from a_domain.types.ids import new_user_id
from a_domain.types.values import EmailAddress, NewPassword, Username
from b_application.config.app_config import AppConfig


class UserRegistration:
    """
    Open registration: a new user with the role USER, while registration is open, inside the limit per client address.
    Every attempt counts, a taken name included, so guessing which names exist is limited too.
    """

    def __init__(
        self, user_store: IUserStore, attempt_log: IAttemptLog, market_clock: IMarketClock, config: AppConfig, logger: ILoggingProvider
    ) -> None:
        self._user_store = user_store
        self._attempt_log = attempt_log
        self._market_clock = market_clock
        self._registration_rule = config.registration_rule()
        self._limit = config.accounts.registration_limit()
        self._logger = logger

    async def execute(self, username: Username, email: EmailAddress, password: NewPassword, client: str) -> User:
        if (closed := self._registration_rule.apply(await self._user_store.user_count())) is not None:
            raise RegistrationClosed(closed)

        now, key = self._market_clock.now(), AttemptKey(limit=AttemptLimit.REGISTRATION, client=client)

        if retry_at := await self._attempt_log.admit(now, {key: self._limit}):
            raise SignInThrottled(retry_at, now)

        user = User(user_id=new_user_id(), username=username, email=email, role=Role.USER, created_at=now)
        await self._user_store.create(user, password)
        self._logger.info(f"User registered: {user.user_id}.")

        return user
