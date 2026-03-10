from typing import Protocol

from a_domain.model.chat.ai_model import AIModel


class IModelCatalogRepository(Protocol):
    async def list_chat_models(self) -> tuple[AIModel, ...]: ...
