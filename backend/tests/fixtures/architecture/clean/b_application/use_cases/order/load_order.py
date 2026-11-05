from uuid import UUID

from a_domain.model.order.order import Order
from a_domain.ports.order import IOrderRepository


class LoadOrderUseCase:
    def __init__(self, repository: IOrderRepository) -> None:
        self._repository = repository

    async def execute(self, order_id: UUID) -> Order | None:
        return await self._repository.get(order_id)
