from typing import Protocol
from uuid import UUID

from a_domain.model.order.order import Order


class IOrderRepository(Protocol):
    async def get(self, order_id: UUID) -> Order | None: ...

    async def save(self, order: Order) -> None: ...
