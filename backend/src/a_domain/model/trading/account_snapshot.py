from collections.abc import Mapping
from datetime import datetime
from typing import Self
from uuid import UUID, uuid4

from sqlmodel import Field, SQLModel

from a_domain.model.trading.account import Account
from a_domain.model.trading.order import Order
from a_domain.types.ids import OrderId, RunId


class PositionSnapshot(SQLModel):
    """One position at snapshot time, marked at the latest price the run knew for it."""

    stock_id: str
    quantity: int = Field(gt=0)
    average_cost: float = Field(gt=0)
    mark_price: float = Field(gt=0)

    @property
    def market_value(self) -> float:
        return self.quantity * self.mark_price


class AccountSnapshot(SQLModel):
    """Cash and positions right after a fill. All snapshots in time order are the account's history."""

    snapshot_id: UUID = Field(default_factory=uuid4)
    taken_at: datetime
    run_id: RunId
    order_id: OrderId
    cash: float = Field(ge=0)
    positions: list[PositionSnapshot] = Field(default_factory=list)

    @property
    def market_value(self) -> float:
        return sum(position.market_value for position in self.positions)

    @property
    def equity(self) -> float:
        return self.cash + self.market_value

    @classmethod
    def after_fill(cls, order: Order, account: Account, latest_prices: Mapping[str, float], taken_at: datetime) -> Self:
        """The filled stock is marked at its fill price, others at the run's latest price, else at their average cost."""
        marks = {**latest_prices, order.stock_id: order.average_filled_price or order.limit_price}

        return cls(
            taken_at=taken_at,
            run_id=order.run_id,
            order_id=order.id,
            cash=account.cash,
            positions=[
                PositionSnapshot(
                    stock_id=position.stock_id,
                    quantity=position.quantity,
                    average_cost=position.average_cost,
                    mark_price=marks.get(position.stock_id) or position.average_cost,
                )
                for position in account.positions
            ],
        )
