import asyncio

import httpx
from openai import AsyncOpenAI, OpenAIError

from a_domain.model.chat.ai_model import AIModel
from a_domain.ports.chat.model_catalog_repository import IModelCatalogRepository
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.types.enums import AiProvider
from b_application.config.app_config import AppConfig


class ModelsCatalog(IModelCatalogRepository):
    def __init__(self, config: AppConfig, logger: ILoggingProvider):
        self._config = config
        self._logger = logger
        self._timeout = httpx.Timeout(self._config.ai.connection_timeout)
        self._openai_client = (
            AsyncOpenAI(api_key=self._config.ai.openai_api_key, timeout=self._timeout) if self._config.ai.openai_api_key else None
        )
        self._xai_client = (
            AsyncOpenAI(api_key=self._config.ai.grok_api_key, base_url=self._config.sources.ai.grok_base_url, timeout=self._timeout)
            if self._config.ai.grok_api_key
            else None
        )

    async def _fetch_openai_models(self) -> tuple[AIModel, ...]:
        if not self._openai_client:
            self._logger.debug("OpenAI API key not configured. Skipping model fetch.")
            return tuple()
        self._logger.debug("Fetching models from OpenAI...")
        try:
            response = await self._openai_client.models.list()
            models = tuple(AIModel(provider=AiProvider.OPENAI, name=model.id) for model in response.data if "gpt" in model.id)
            self._logger.info(f"Found {len(models)} compatible models from OpenAI.")
            return models
        except OpenAIError as error:
            self._logger.error(f"OpenAI API error while listing models: {error}")
            return tuple()
        except Exception as error:
            self._logger.critical(f"Unexpected error fetching OpenAI models: {error}")
            return tuple()

    async def _fetch_grok_models(self) -> tuple[AIModel, ...]:
        if not self._xai_client:
            self._logger.debug("Grok API key not configured. Skipping model fetch.")
            return tuple()
        self._logger.debug("Fetching models from Grok (X.ai)...")
        try:
            response = await self._xai_client.models.list()
            models = tuple(AIModel(provider=AiProvider.GROK, name=model.id) for model in response.data)
            self._logger.info(f"Found {len(models)} models from Grok (X.ai).")
            return models
        except OpenAIError as error:
            self._logger.error(f"Grok API error while listing models: {error}")
            return tuple()
        except Exception as error:
            self._logger.critical(f"Unexpected error fetching Grok models: {error}")
            return tuple()

    async def list_chat_models(self) -> tuple[AIModel, ...]:
        self._logger.info("Starting to fetch model lists from all configured providers.")
        tasks = []
        if self._openai_client:
            tasks.append(self._fetch_openai_models())
        if self._xai_client:
            tasks.append(self._fetch_grok_models())
        if not tasks:
            self._logger.warning("No AI providers are configured with API keys. Cannot fetch any models.")
            return tuple()
        results = await asyncio.gather(*tasks, return_exceptions=True)
        all_models: list[AIModel] = []
        for result in results:
            if isinstance(result, Exception):
                self._logger.error(f"A task failed during model fetching: {result}")
            elif isinstance(result, tuple):
                all_models.extend(result)
        sorted_models = sorted(all_models, key=lambda model: (model.provider.value, model.name))
        self._logger.success(f"Total unique models fetched from all providers: {len(sorted_models)}")
        return tuple(sorted_models)
