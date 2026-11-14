from typing import override

from a_domain.ports.market.price_provider import IPriceProvider


class YahooPriceProvider(IPriceProvider):
    @override
    async def fetch(self, stock_id: str) -> float:
        return parse_price(stock_id)

    @override
    async def fetch_history(self, stock_id: str) -> list[float]:
        return [parse_price(stock_id)]

    @override
    async def __aenter__(self) -> "YahooPriceProvider":
        return self


def parse_price(raw: str) -> float:
    return float(raw)
