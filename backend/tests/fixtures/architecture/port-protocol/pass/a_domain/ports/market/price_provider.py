import typing


class IPriceProvider(typing.Protocol):
    async def fetch(self, stock_id: str) -> float: ...
