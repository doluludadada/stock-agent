from typing import override

from a_domain.ports.market import IPriceProvider


class YahooPriceProvider(IPriceProvider):
    def __init__(self, timeout: float) -> None:
        self._timeout = timeout

    @override
    async def fetch(self, stock_id: str) -> float:
        return self._parse(stock_id)

    async def fetch_history(self, stock_id: str) -> list[float]:
        return []

    def _parse(self, raw: str) -> float:
        return float(raw)

    def __parse_row(self, raw: str) -> float:
        return float(raw)

    async def __aenter__(self) -> "YahooPriceProvider":
        return self


class PriceCache:
    def get(self, stock_id: str) -> float | None:
        return None
