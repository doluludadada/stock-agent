from typing import override

from a_domain.ports.market.price_provider import IPriceProvider


class YahooPriceProvider(IPriceProvider):
    @override
    async def fetch(self, stock_id: str) -> float:
        return self.parse_price(stock_id)

    @override
    def parse_price(self, raw: str) -> float:
        return float(raw)

    @override
    async def __aenter__(self) -> "YahooPriceProvider":
        return self
