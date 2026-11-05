from a_domain.ports.system.user_store import IUserStore
from a_domain.rules.system.registration import SignInOffer
from b_application.config.app_config import AppConfig


class SignInOptions:
    """What the sign-in screen offers: the first-time setup while no user exists, and registration while it is open."""

    def __init__(self, user_store: IUserStore, config: AppConfig) -> None:
        self._user_store = user_store
        self._registration_rule = config.registration_rule()

    async def execute(self) -> SignInOffer:
        user_count = await self._user_store.user_count()

        return SignInOffer(
            needs_first_administrator=user_count == 0, registration_open=self._registration_rule.apply(user_count) is None
        )
