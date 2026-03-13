from a_domain.ports.chat.web_search_provider import IWebSearchProvider
from a_domain.ports.ai.ai_provider import IAiProvider
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.types.enums import AiProvider
from b_application.schemas.config import AppConfig
from c_infrastructure.ai_models.ai_adapter.gemini_adapter import GeminiAIAdapter
from c_infrastructure.ai_models.ai_adapter.grok_adapter import GrokAdapter
from c_infrastructure.ai_models.ai_adapter.groq_adapter import GroqAIAdapter
from c_infrastructure.ai_models.ai_adapter.openai_adapter import OpenAIAdapter


class AiAdapterFactory:
    """
    Factory class responsible for creating AI model adapter instances based on configuration.
    """

    def __init__(self, config: AppConfig, logger: ILoggingProvider, web_search: IWebSearchProvider | None = None):
        self._config = config
        self._logger = logger
        self._web_search = web_search
        self._logger.trace(f"AI Adapter Factory initialised. Active model provider: {self._config.ai.active_model.value}")

    def create_adapter(
        self, *, override_provider: AiProvider | None = None, override_model_name: str | None = None
    ) -> IAiProvider:
        provider = override_provider or self._config.ai.active_model
        model_name = override_model_name or self._config.ai.available_models.get(provider)

        if model_name is None:
            raise ValueError(
                f"No model id resolved for provider {provider!s}. "
                "Configure available_models or enable remote catalogue."
            )

        self._logger.debug(f"Creating AI adapter for provider: {provider.value} with model: {model_name}")

        if provider == AiProvider.OPENAI:
            return OpenAIAdapter(
                config=self._config,
                logger=self._logger,
                model_name=model_name,
            )

        if provider == AiProvider.GROK:
            return GrokAdapter(
                config=self._config,
                logger=self._logger,
                model_name=model_name,
            )

        if provider == AiProvider.GEMINI:
            return GeminiAIAdapter(
                config=self._config,
                logger=self._logger,
                model_name=model_name,
            )
        
        if provider == AiProvider.GROQ:
            return GroqAIAdapter(
                config=self._config,
                logger=self._logger,
                model_name=model_name,
                web_search=self._web_search,
            )
        raise ValueError(f"Unsupported provider: {provider!s}")


