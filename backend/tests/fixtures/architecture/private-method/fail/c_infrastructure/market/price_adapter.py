from typing import override

from a_domain.ports.market import IPriceProvider


class YahooPriceProvider(IPriceProvider):
    @override
    async def fetch(self, stock_id: str) -> float:
        return self._parse(stock_id) + self.__parse_row(stock_id)

    def _parse(self, raw: str) -> float:
        return float(raw)

    def __parse_row(self, raw: str) -> float:
        return float(raw)

    async def _download(self, stock_id: str) -> str:
        return stock_id
