from a_domain.ports.order import IOrderRepository
from a_domain.rules.shipping.free_shipping import FreeShippingRule
from b_application.config.settings import ShippingSettings
from b_application.schemas.pipeline_status import PipelineStatus


class PlaceOrderUseCase:
    def __init__(self, repository: IOrderRepository, settings: ShippingSettings) -> None:
        self._repository = repository
        self._free_shipping = FreeShippingRule(settings.minimum_total, settings.excluded_regions)

    async def execute(self, status: PipelineStatus) -> None:
        order = status.require_order()
        status.free_shipping = self._free_shipping.apply(order, status.region)
        await self._repository.save(order)
