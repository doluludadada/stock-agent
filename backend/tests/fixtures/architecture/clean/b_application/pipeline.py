from dataclasses import dataclass
from uuid import UUID

from a_domain.ports.system.logging_provider import ILoggingProvider
from b_application.schemas.pipeline_status import PipelineStatus
from b_application.use_cases.order.load_order import LoadOrderUseCase
from b_application.use_cases.order.place_order import PlaceOrderUseCase


@dataclass
class Pipeline:
    load_order: LoadOrderUseCase
    place_order: PlaceOrderUseCase
    logger: ILoggingProvider

    async def checkout(self, order_id: UUID, region: str) -> PipelineStatus:
        status = PipelineStatus(order_id=order_id, region=region)
        status.order = await self.load_order.execute(order_id)
        status.free_shipping = await self.place_order.execute(status)
        self.logger.info(f"Order {order_id} placed.")
        return status
