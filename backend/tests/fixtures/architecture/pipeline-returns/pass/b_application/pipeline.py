from dataclasses import dataclass

from b_application.schemas.order import OrderTotal
from b_application.use_cases.order.load_order import LoadOrderUseCase


@dataclass
class Pipeline:
    load_order: LoadOrderUseCase

    async def load_order_total(self, order_id: str) -> OrderTotal:
        return OrderTotal(order_id, 0.0)

    async def find_order_total(self, order_id: str) -> OrderTotal | None:
        return None

    def list_sections(self) -> list[str]:
        return []

    async def load_trades(self) -> list[tuple[str, float]]:
        return []


def pair_of(order_id: str) -> tuple[str, str]:
    return order_id, order_id
