from datetime import UTC, datetime
from typing import ClassVar

from sqlmodel import Field, SQLModel

from c_infrastructure.database.utc_datetime import UtcDateTime


class MockCash(SQLModel, table=True):
    """The mock broker's cash. Its history lives in account_snapshots, which the app writes after every fill."""

    __tablename__: ClassVar[str] = "mock_cash"

    account_id: str = Field(primary_key=True)
    current_cash: float = Field(ge=0)
    initial_cash: float = Field(ge=0)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC), sa_type=UtcDateTime)
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC), sa_type=UtcDateTime)


class MockPosition(SQLModel, table=True):
    """The mock broker's open positions. Their history, market value and PnL live in account_snapshots."""

    __tablename__: ClassVar[str] = "mock_positions"

    account_id: str = Field(primary_key=True)
    stock_id: str = Field(primary_key=True)
    quantity: int = Field(gt=0)
    average_cost: float = Field(gt=0)
    opened_at: datetime = Field(default_factory=lambda: datetime.now(UTC), sa_type=UtcDateTime)
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC), sa_type=UtcDateTime)
