from b_application.schemas.pipeline_status import PipelineStatus
from b_application.use_cases.order.place_order import PlaceOrderUseCase


class Pipeline:
    def __init__(self, place_order: PlaceOrderUseCase) -> None:
        self._place_order = place_order

    async def place_order(self, status: PipelineStatus) -> PipelineStatus:
        await self._place_order.execute(status)
        return status
