import math
from datetime import datetime

from sqlmodel import Field, SQLModel


class Position(SQLModel):
    """Broker/account ownership state."""

    stock_id: str = Field(min_length=1)
    quantity: int = Field(gt=0)
    average_cost: float = Field(gt=0)

    opened_at: datetime | None = None

    updated_at: datetime = Field(default_factory=datetime.now)

    @property
    def cost_basis(self) -> float:
        return self.quantity * self.average_cost

    def can_cover(self, quantity: int) -> bool:
        if quantity <= 0:
            raise ValueError("Quantity must be positive")

        return self.quantity >= quantity

    def add(
        self,
        quantity: int,
        price: float,
    ) -> None:
        if quantity <= 0:
            raise ValueError("Quantity must be positive")

        if not math.isfinite(price) or price <= 0:
            raise ValueError("Price must be positive")

        total_quantity = self.quantity + quantity
        self.average_cost = (self.cost_basis + quantity * price) / total_quantity
        self.quantity = total_quantity
        self.updated_at = datetime.now()

    def remaining_after_sell(self, quantity: int) -> int:
        if not self.can_cover(quantity):
            raise ValueError("Position quantity is insufficient")

        return self.quantity - quantity

    def reduce(
        self,
        quantity: int,
    ) -> None:
        remaining_quantity = self.remaining_after_sell(quantity)

        if remaining_quantity == 0:
            raise ValueError("Cannot reduce an active position to zero")

        self.quantity = remaining_quantity
        self.updated_at = datetime.now()
