from typing import Protocol

from a_domain.ports.trading.execution_provider import IExecutionProvider


class IPaperExecutionProvider(IExecutionProvider, Protocol):
    async def reset(self) -> None: ...
