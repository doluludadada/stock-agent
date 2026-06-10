from typing import Protocol
from uuid import UUID

from a_domain.model.trading.order import Order
from a_domain.model.trading.position import Position


class IExecutionProvider(Protocol):
    """Executes orders and exposes broker account state."""

    async def place_order(self, order: Order) -> Order: ...

    async def cancel_order(self, order_id: UUID) -> Order | None: ...

    async def get_positions(self) -> list[Position]: ...

    async def get_cash_balance(self) -> float: ...
