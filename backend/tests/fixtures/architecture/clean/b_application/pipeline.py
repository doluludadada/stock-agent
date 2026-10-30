from b_application.schemas.pipeline_status import PipelineStatus
from b_application.use_cases.order.load_order import LoadOrderUseCase
from b_application.use_cases.order.place_order import PlaceOrderUseCase


class Pipeline:
    def __init__(self, load_order: LoadOrderUseCase, place_order: PlaceOrderUseCase) -> None:
        self._load_order = load_order
        self._place_order = place_order

    async def place_order(self, status: PipelineStatus) -> PipelineStatus:
        await self._load_order.execute(status)
        await self._place_order.execute(status)
        return status
