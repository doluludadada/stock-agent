import math
from datetime import datetime

from sqlmodel import Field, SQLModel

from a_domain.model.trading.position import Position


class Account(SQLModel):
    """
    Cash and positions held at the broker.

    Cash settles at the fill: T+2 settlement and margin are not modeled, and there are no pending
    orders (the app sends IOC only). Fees and tax reach the account through the amounts each trade
    settles with, which TradingCostRule computes.
    """

    account_id: str = Field(default="default", min_length=1)

    cash: float = Field(default=0, ge=0)
    positions: list[Position] = Field(default_factory=list)

    updated_at: datetime = Field(default_factory=datetime.now)

    def can_afford(self, amount: float) -> bool:
        if not math.isfinite(amount) or amount < 0:
            raise ValueError("Amount must be a finite non-negative number")

        return self.cash >= amount

    def position_for(self, stock_id: str) -> Position | None:
        for position in self.positions:
            if position.stock_id == stock_id:
                return position

        return None

    def buy(self, stock_id: str, quantity: int, price: float, total_cost: float) -> Position:
        """Pays `total_cost` (gross plus fee) for shares traded at `price`. The whole cost, fee included, is the cost basis."""
        if not stock_id.strip():
            raise ValueError("stock_id is required")

        if quantity <= 0:
            raise ValueError("Quantity must be positive")

        if not math.isfinite(price) or price <= 0:
            raise ValueError("Price must be positive")

        if not math.isfinite(total_cost) or total_cost < price * quantity:
            raise ValueError("Total cost cannot be below the traded value")

        if not self.can_afford(total_cost):
            raise ValueError("Insufficient cash")

        position = self.position_for(stock_id)

        if position is None:
            position = Position(stock_id=stock_id, quantity=quantity, average_cost=total_cost / quantity)
            self.positions.append(position)

        else:
            position.add(quantity=quantity, price=total_cost / quantity)

        self.cash -= total_cost
        self.updated_at = datetime.now()

        return position

    def sell(self, stock_id: str, quantity: int, cash_delta: float) -> int:
        """Receives `cash_delta` (gross minus fee and tax) and returns the shares left in the position."""
        if not stock_id.strip():
            raise ValueError("stock_id is required")

        if quantity <= 0:
            raise ValueError("Quantity must be positive")

        if not math.isfinite(cash_delta) or self.cash + cash_delta < 0:
            raise ValueError("Cash delta must be finite and keep cash non-negative")

        position = self.position_for(stock_id)

        if position is None:
            raise ValueError(f"Position not found: {stock_id}")

        remaining_quantity = position.remaining_after_sell(quantity)

        if remaining_quantity == 0:
            self.positions.remove(position)

        else:
            position.reduce(quantity)

        self.cash += cash_delta
        self.updated_at = datetime.now()

        return remaining_quantity
