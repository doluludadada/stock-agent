import typing

from pydantic.dataclasses import dataclass


@dataclass(frozen=True)
class Quote:
    price: float


class IPriceProvider(typing.Protocol):
    async def fetch(self, stock_id: str) -> Quote: ...
