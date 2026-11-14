from typing import override

from a_domain.ports.market.price_provider import ICachedPriceProvider


class CachedPriceProvider(ICachedPriceProvider):
    @override
    async def fetch(self, stock_id: str) -> float:
        await self.refresh()
        return self.parse_price(stock_id)

    @override
    def parse_price(self, raw: str) -> float:
        return float(raw)

    @override
    async def refresh(self) -> None:
        return None

    @override
    def stale(self) -> bool:
        return False

    @override
    async def __aenter__(self) -> "CachedPriceProvider":
        return self
