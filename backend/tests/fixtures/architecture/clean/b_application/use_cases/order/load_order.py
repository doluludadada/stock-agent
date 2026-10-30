from a_domain.ports.order import IOrderRepository
from b_application.schemas.pipeline_status import PipelineStatus


class LoadOrderUseCase:
    def __init__(self, repository: IOrderRepository) -> None:
        self._repository = repository

    async def execute(self, status: PipelineStatus) -> None:
        status.order = await self._repository.get(status.order_id)
