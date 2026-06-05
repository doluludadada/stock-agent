from datetime import datetime, timezone
from typing import ClassVar
from uuid import UUID, uuid4

from sqlmodel import Field, SQLModel

from a_domain.types.enums import OrderStatus, OrderType, TradeAction
from c_infrastructure.trading.mock.constants import MockTableName


class MockCash(SQLModel, table=True):
    __tablename__: ClassVar[str] = MockTableName.CASH  # pyright: ignore[reportIncompatibleVariableOverride]

    account_id: str = Field(primary_key=True)
    current_cash: float = Field(ge=0)
    initial_cash: float = Field(ge=0)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    # TODO: Phase 2.5 - add cash snapshot history for UI / audit.


class MockPosition(SQLModel, table=True):
    __tablename__: ClassVar[str] = MockTableName.POSITIONS  # pyright: ignore[reportIncompatibleVariableOverride]

    account_id: str = Field(primary_key=True)
    stock_id: str = Field(primary_key=True)
    quantity: int = Field(gt=0)
    average_cost: float = Field(gt=0)
    opened_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    # TODO: Phase 2.5 - add position snapshot table for portfolio history.
    # TODO: Future - add market_value and unrealized_pnl.


class MockOrder(SQLModel, table=True):
    __tablename__: ClassVar[str] = MockTableName.ORDERS  # pyright: ignore[reportIncompatibleVariableOverride]

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    account_id: str = Field(index=True)
    stock_id: str = Field(index=True)
    action: TradeAction
    order_type: OrderType
    price: float
    quantity: int
    status: OrderStatus
    reason: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    # TODO: Phase 2.5 - add run_id.
    # TODO: Phase 2.5 - add decision_id.
    # TODO: Future - add fee, tax, realized_pnl.
