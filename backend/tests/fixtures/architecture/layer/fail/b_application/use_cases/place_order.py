import d_presentation.dependencies
from a_domain.model.order import Order
from c_infrastructure.database.order_repository import SqlOrderRepository


class PlaceOrderUseCase:
    def execute(self, order: Order) -> None:
        return None
