from abc import ABC
from datetime import datetime
from typing import override

from a_domain.ports.ai.ai_provider import IAiProvider
from a_domain.ports.system.logging_provider import ILoggingProvider
from b_application.config.app_config import AppConfig


class BaseAIAdapter(IAiProvider, ABC):
    """What every AI model adapter shares: its settings, its model name, and where it saves raw replies."""

    def __init__(self, config: AppConfig, logger: ILoggingProvider, model_name: str):
        self._config = config
        self._logger = logger
        self._model_name = model_name

    @override
    def save_response(self, stock_id: str, content: str) -> None:
        """Saves the raw AI response to the filesystem for inspection."""
        try:
            stock_dir = self._config.project_root / self._config.folder.ai_response_dir / stock_id
            stock_dir.mkdir(parents=True, exist_ok=True)
            file_path = stock_dir / f"report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"

            with open(file_path, "w", encoding="utf-8") as file:
                file.write(content)

            self._logger.debug(f"[{self.__class__.__name__}] Saved AI response for {stock_id} to {file_path}")
        except Exception as error:
            self._logger.error(f"[{self.__class__.__name__}] Failed to save AI response for {stock_id}: {error}")
