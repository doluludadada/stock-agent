from dataclasses import dataclass
from uuid import UUID

from a_domain.model.order.order import Order


@dataclass
class PipelineStatus:
    order_id: UUID
    region: str
    order: Order | None = None
    free_shipping: bool = False

    def require_order(self) -> Order:
        if self.order is None:
            raise LookupError(f"order {self.order_id} was not loaded")

        return self.order
