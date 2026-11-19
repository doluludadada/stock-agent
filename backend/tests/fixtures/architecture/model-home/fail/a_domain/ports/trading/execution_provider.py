from typing import Protocol

from a_domain.model.trading.order import ExchangeOrder, Order


class IBrokerExecutionProvider(Protocol):
    async def send(self, order: Order) -> list[ExchangeOrder]: ...
