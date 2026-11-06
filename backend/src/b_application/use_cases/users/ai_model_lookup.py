from a_domain.model.system.user import User
from a_domain.types.enums import AiProvider
from b_application.config.app_config import AppConfig


class AiModelLookup:
    """
    What My settings shows of the AI model: each model the site offers with its model id, the site's default first,
    then the default itself, then the model the user's runs use, their choice while the site offers it, else the
    default: the model dependencies.py runs the user's Pipeline on.
    """

    def __init__(self, config: AppConfig) -> None:
        self._ai = config.ai

    def execute(self, user: User) -> tuple[dict[AiProvider, str], AiProvider, AiProvider]:
        return self._ai.offered_models, self._ai.active_model, self._ai.model_for(user.ai_model)
