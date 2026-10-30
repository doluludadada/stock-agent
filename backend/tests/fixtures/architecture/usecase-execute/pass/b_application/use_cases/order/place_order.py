from a_domain.model.order import Order
from a_domain.ports.order import IOrderRepository
from b_application.schemas.pipeline_status import PipelineStatus


class PlaceOrderUseCase:
    def __init__(self, repository: IOrderRepository) -> None:
        self._repository = repository

    async def execute(self, status: PipelineStatus) -> None:
        order: Order = status.require_order()
        await self._repository.save(order)
