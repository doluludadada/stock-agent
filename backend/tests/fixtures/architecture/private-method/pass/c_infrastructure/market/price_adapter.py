from typing import Self, override

from a_domain.ports.market import IPriceProvider


def parse(raw: str) -> float:
    return float(raw)


class YahooPriceProvider(IPriceProvider):
    def __init__(self, timeout: float) -> None:
        self._timeout = timeout

    @override
    async def fetch(self, stock_id: str) -> float:
        return parse(stock_id)

    @override
    async def __aenter__(self) -> Self:
        return self
