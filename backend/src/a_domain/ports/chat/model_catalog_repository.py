from typing import Protocol



class IModelCatalogRepository(Protocol):
    async def list_chat_models(self) -> tuple[AIModel, ...]: ...
