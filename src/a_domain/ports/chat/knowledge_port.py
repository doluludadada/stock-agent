from typing import Protocol


class IKnowledgeBasePort(Protocol):
    async def search(self, query: str, limit: int = 3) -> str: ...
