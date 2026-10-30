from datetime import datetime
from typing import Any, ClassVar
from uuid import UUID

from sqlalchemy import JSON, Column
from sqlmodel import Field, SQLModel

from a_domain.types.enums import ExecutionProvider, OrderMode, OrderStatus, OrderType, SignalSource, TimeInForce, TradeAction, Workflow


class WorkflowRunDTO(SQLModel, table=True):
    """One workflow run (SystemStats). end_time stays empty when the run never finished."""

    __tablename__: ClassVar[str] = "workflow_runs"  # pyright: ignore[reportIncompatibleVariableOverride]

    run_id: UUID = Field(primary_key=True)
    workflow: Workflow
    execution_provider: ExecutionProvider
    order_mode: OrderMode
    start_time: datetime
    end_time: datetime | None = None

    total_scanned: int
    buzz_scanned: int
    buzz_qualified: int
    news_scanned: int
    total_skipped: int
    passed_technical: int
    ai_analysed: int
    signals_generated: int
    orders_submitted: int
    orders_refused: int
    stale_market_data_count: int

    errors: list[str] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    execution_log: list[str] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))


class TradeSignalDTO(SQLModel, table=True):
    """One decision (TradeSignal) with its evidence and the run that made it."""

    __tablename__: ClassVar[str] = "trade_signals"  # pyright: ignore[reportIncompatibleVariableOverride]

    decision_id: UUID = Field(primary_key=True)
    run_id: UUID = Field(index=True)

    stock_id: str = Field(index=True)
    action: TradeAction
    source: SignalSource
    score: int
    reason: str
    quantity: int
    stop_loss_price: float | None = None
    generated_at: datetime

    price_at_signal: float
    price_observed_at: datetime
    history_until: datetime | None = None
    technical_report: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    ai_report: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))


class OrderDTO(SQLModel, table=True):
    """The app's order record (Order). One row per decision, whichever execution provider ran it."""

    __tablename__: ClassVar[str] = "orders"  # pyright: ignore[reportIncompatibleVariableOverride]

    id: UUID = Field(primary_key=True)
    run_id: UUID = Field(index=True)
    decision_id: UUID = Field(unique=True, index=True)

    stock_id: str = Field(index=True)
    action: TradeAction
    order_type: OrderType
    quantity: int
    limit_price: float | None = None
    time_in_force: TimeInForce

    status: OrderStatus
    reason: str | None = None

    filled_quantity: int
    average_filled_price: float | None = None
    fee: int
    tax: int
    realized_pnl: float | None = None

    created_at: datetime
    updated_at: datetime


class AccountSnapshotDTO(SQLModel, table=True):
    """Cash and positions right after the fill of `order_id`."""

    __tablename__: ClassVar[str] = "account_snapshots"  # pyright: ignore[reportIncompatibleVariableOverride]

    snapshot_id: UUID = Field(primary_key=True)
    taken_at: datetime = Field(index=True)
    run_id: UUID = Field(index=True)
    order_id: UUID = Field(index=True)
    cash: float
    positions: list[dict[str, Any]] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
