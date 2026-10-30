import typing
from typing import override

from a_domain.ports.market import IPriceProvider


class YahooPriceProvider(IPriceProvider):
    def __init__(self, timeout: float) -> None:
        self._timeout = timeout

    @override
    async def fetch(self, stock_id: str) -> float:
        return self.parse_price(stock_id)

    @typing.override
    def parse_price(self, raw: str) -> float:
        return float(raw)

    @override
    async def __aenter__(self) -> "YahooPriceProvider":
        return self
