from typing import Protocol


class ILoggingProvider(Protocol):
    def info(self, message: str) -> None: ...
