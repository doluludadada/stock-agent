from a_domain.model.system.user import User
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.system.market_clock import IMarketClock
from a_domain.ports.system.user_store import IUserStore
from a_domain.types.enums import AiProvider
from a_domain.types.errors import AiModelNotOffered
from b_application.config.app_config import AppConfig


class AiModelChoice:
    """
    A user's choice on My settings of the AI model their runs use: one the site offers, ai.active_model or one of
    ai.user_selectable, or None for the site's default. A model the site does not offer is refused and nothing is saved
    (AiModelNotOffered). The user's next Pipeline runs on the choice; a run already running keeps its model.
    """

    def __init__(self, user_store: IUserStore, market_clock: IMarketClock, config: AppConfig, logger: ILoggingProvider) -> None:
        self._user_store = user_store
        self._market_clock = market_clock
        self._ai = config.ai
        self._logger = logger

    async def execute(self, user: User, ai_model: AiProvider | None) -> User:
        """The user with the choice saved."""
        if ai_model is not None and ai_model not in self._ai.offered_models:
            offered = ", ".join(provider.label for provider in self._ai.offered_models)
            raise AiModelNotOffered(f"This site does not offer {ai_model.label}. Choose one of: {offered}.")

        await self._user_store.save_ai_model(user.user_id, ai_model, self._market_clock.now())
        user.ai_model = ai_model
        self._logger.info(f"User {user.user_id} chose the AI model: {ai_model.value if ai_model else 'site default'}.")

        return user
