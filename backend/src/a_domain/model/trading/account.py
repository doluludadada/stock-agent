import math
from datetime import datetime

from sqlmodel import Field, SQLModel

from a_domain.model.trading.position import Position


class Account(SQLModel):
    """Current account state enriched by application services."""

    account_id: str = Field(default="default", min_length=1)

    cash: float = Field(default=0, ge=0)
    """
    TODO:

    Future account constraints:
    - unsettled cash
    - pending orders
    - fees
    - tax
    - margin limits

    """

    positions: list[Position] = Field(default_factory=list)
    """
    What do I have in this acoount
    """

    updated_at: datetime = Field(default_factory=datetime.now)

    # ---------------------------------------------------------------------------- #
    #                                   Functions                                  #
    # ---------------------------------------------------------------------------- #
    def can_afford(self, amount: float) -> bool:
        if not math.isfinite(amount) or amount < 0:
            raise ValueError("Amount must be a finite non-negative number")

        return self.cash >= amount

    def debit(self, amount: float) -> None:
        if not math.isfinite(amount) or amount <= 0:
            raise ValueError("Amount must be positive")

        if not self.can_afford(amount):
            raise ValueError("Insufficient cash")

        self.cash -= amount
        self.updated_at = datetime.now()

    def apply_cash_delta(self, delta: float) -> None:
        if not math.isfinite(delta):
            raise ValueError("Cash delta must be finite")

        if self.cash + delta < 0:
            raise ValueError("Insufficient cash")

        if delta == 0:
            return

        self.cash += delta
        self.updated_at = datetime.now()

    def position_for(self, stock_id: str) -> Position | None:
        for position in self.positions:
            if position.stock_id == stock_id:
                return position

        return None

    def buy(
        self,
        stock_id: str,
        quantity: int,
        price: float,
        total_cost: float,
    ) -> Position:
        if not stock_id.strip():
            raise ValueError("stock_id is required")

        if quantity <= 0:
            raise ValueError("Quantity must be positive")

        if not math.isfinite(price) or price <= 0:
            raise ValueError("Price must be positive")

        self.debit(total_cost)

        position = self.position_for(stock_id)

        if position is None:
            position = Position(
                stock_id=stock_id,
                quantity=quantity,
                average_cost=price,
            )
            self.positions.append(position)

        else:
            position.add(
                quantity=quantity,
                price=price,
            )

        self.updated_at = datetime.now()

        return position

    def sell(
        self,
        stock_id: str,
        quantity: int,
        cash_delta: float,
    ) -> int:
        if not stock_id.strip():
            raise ValueError("stock_id is required")

        if quantity <= 0:
            raise ValueError("Quantity must be positive")

        if not math.isfinite(cash_delta):
            raise ValueError("Cash delta must be finite")

        if self.cash + cash_delta < 0:
            raise ValueError("Insufficient cash")

        position = self.position_for(stock_id)

        if position is None:
            raise ValueError(f"Position not found: {stock_id}")

        remaining_quantity = position.remaining_after_sell(quantity)

        if remaining_quantity == 0:
            self.positions.remove(position)

        else:
            position.reduce(quantity)

        self.apply_cash_delta(cash_delta)
        self.updated_at = datetime.now()

        return remaining_quantity
