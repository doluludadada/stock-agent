from abc import ABC, abstractmethod
from datetime import datetime

from a_domain.model.chat.message import Message, MessageRole
from a_domain.ports.ai.ai_provider import IAiProvider
from a_domain.ports.system.logging_provider import ILoggingProvider
from b_application.schemas.config import AppConfig


class BaseAIAdapter(IAiProvider, ABC):
    """
    An abstract base class for AI model adapters.
    """

    def __init__(self, config: AppConfig, logger: ILoggingProvider, model_name: str):
        self._config = config
        self._logger = logger
        self._model_name = model_name

    @abstractmethod
    async def _call_api(self, messages: tuple[Message, ...]) -> str: ...

    async def generate_reply(self, messages: tuple[Message, ...]) -> Message:
        """Orchestrates the reply generation process (Template Method)."""
        self._logger.debug(f"[{self.__class__.__name__}] Generating reply with model: {self._model_name}")
        self._logger.trace(f"[{self.__class__.__name__}] Sending {len(messages)} messages to model.")

        try:
            reply_content = await self._call_api(messages)
            self._logger.success(
                f"[{self.__class__.__name__}] Successfully received reply from model: {self._model_name}"
            )
            return Message(role=MessageRole.ASSISTANT, content=reply_content)
        except Exception as e:
            self._logger.critical(f"[{self.__class__.__name__}] An unexpected critical error occurred: {e}")
            return Message(
                role=MessageRole.ASSISTANT,
                content="I've encountered an unexpected error. The technical team has been notified.",
            )

    def save_response(self, stock_id: str, content: str) -> None:
        """Saves the raw AI response to the filesystem for inspection."""
        try:
            base_dir = self._config.project_root / self._config.ai.ai_response_dir
            stock_dir = base_dir / stock_id
            stock_dir.mkdir(parents=True, exist_ok=True)

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"report_{timestamp}.md"
            file_path = stock_dir / filename

            with open(file_path, "w", encoding="utf-8") as f:
                f.write(content)

            self._logger.debug(f"[{self.__class__.__name__}] Saved AI response for {stock_id} to {file_path}")
        except Exception as e:
            self._logger.error(f"[{self.__class__.__name__}] Failed to save AI response for {stock_id}: {e}")
