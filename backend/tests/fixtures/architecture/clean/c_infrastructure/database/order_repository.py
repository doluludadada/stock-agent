from typing import override
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from a_domain.model.order.order import Order
from a_domain.ports.order import IOrderRepository
from c_infrastructure.database.models.order_row import OrderRow


class SqlOrderRepository(IOrderRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @override
    async def get(self, order_id: UUID) -> Order | None:
        row = await self._session.get(OrderRow, order_id)
        return row.to_domain() if row else None

    @override
    async def save(self, order: Order) -> None:
        self._session.add(OrderRow(id=order.id, customer_id=order.customer_id, total=order.total, version=order.version))
        await self._session.commit()
