from typing import Protocol, TypeVar

ModelT = TypeVar("ModelT")


class IRepository(Protocol[ModelT]):
    async def get(self, key: str) -> ModelT | None: ...
