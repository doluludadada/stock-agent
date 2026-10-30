from a_domain.model.order import Order
from b_application.schemas.pipeline_status import PipelineStatus


class PlaceOrderUseCase:
    def execute(self, status: PipelineStatus) -> Order | None:
        return status.order
