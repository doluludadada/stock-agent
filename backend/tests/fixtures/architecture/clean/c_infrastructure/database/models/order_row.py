from uuid import UUID

from sqlmodel import Field, SQLModel

from a_domain.model.order.order import Order


class OrderRow(SQLModel, table=True):
    id: UUID = Field(primary_key=True)
    customer_id: UUID
    total: int
    version: int

    def to_domain(self) -> Order:
        return Order(id=self.id, customer_id=self.customer_id, total=self.total, version=self.version)
