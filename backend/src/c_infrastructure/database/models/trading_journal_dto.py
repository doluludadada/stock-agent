from datetime import datetime
from typing import Any, ClassVar, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict
from sqlalchemy import JSON, Column
from sqlmodel import Field, SQLModel

from a_domain.model.analysis.ai_analysis_report import AiAnalysisReport
from a_domain.model.analysis.technical_report import TechnicalReport
from a_domain.model.market.ohlcv import Ohlcv
from a_domain.model.market.stock import Stock
from a_domain.model.trading.account import Account, AccountSnapshot, Mark, Position
from a_domain.types.enums import ExecutionProvider, OrderMode, OrderStatus, OrderType, SignalSource, TimeInForce, TradeAction, Workflow
from a_domain.types.ids import OrderId, RunId
from c_infrastructure.database.utc_datetime import UtcDateTime


class WorkflowRunDTO(SQLModel, table=True):
    """One workflow run (SystemStats). end_time stays empty when the run never finished."""

    __tablename__: ClassVar[str] = "workflow_runs"

    run_id: UUID = Field(primary_key=True)
    workflow: Workflow
    execution_provider: ExecutionProvider
    order_mode: OrderMode
    start_time: datetime = Field(sa_type=UtcDateTime)
    end_time: datetime | None = Field(default=None, sa_type=UtcDateTime)
    technical_strategy_id: str | None = None
    ai_model: str | None = None

    total_scanned: int
    buzz_scanned: int
    buzz_qualified: int
    sentiment_analysed: int = 0
    passed_technical: int
    ai_analysed: int
    signals_generated: int
    orders_submitted: int
    orders_filled: int = 0
    orders_refused: int
    stale_market_data_count: int

    errors: list[str] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    execution_log: list[str] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    failure: str | None = None


class TradeSignalDTO(SQLModel, table=True):
    """One decision (TradeSignal) with its evidence and the run that made it."""

    __tablename__: ClassVar[str] = "trade_signals"

    decision_id: UUID = Field(primary_key=True)
    run_id: UUID = Field(index=True)

    stock_id: str = Field(index=True)
    action: TradeAction
    source: SignalSource
    score: int
    reason: str
    quantity: int
    stop_loss_price: float | None = None
    generated_at: datetime = Field(sa_type=UtcDateTime)

    price_at_signal: float
    price_observed_at: datetime = Field(sa_type=UtcDateTime)
    history_until: datetime | None = Field(default=None, sa_type=UtcDateTime)
    technical_report: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    ai_report: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))


class OrderDTO(SQLModel, table=True):
    """The app's order record (Order). One row per decision, whichever execution provider ran it."""

    __tablename__: ClassVar[str] = "orders"

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

    created_at: datetime = Field(sa_type=UtcDateTime)
    updated_at: datetime = Field(sa_type=UtcDateTime)


class SnapshotPositionJson(BaseModel):
    """
    One item of account_snapshots.positions, in the shape the column has always stored. A position without a mark stores
    its average cost as mark_price and no marked_at. unrealized_pnl is always 0: a snapshot keeps no PnL.
    """

    stock_id: str
    quantity: int
    average_cost: float
    mark_price: float
    marked_at: datetime | None
    unrealized_pnl: float

    @classmethod
    def from_domain(cls, position: Position) -> Self:
        return cls(
            stock_id=position.stock_id,
            quantity=position.quantity,
            average_cost=position.average_cost,
            mark_price=position.mark_price,
            marked_at=position.marked_at,
            unrealized_pnl=0.0,
        )

    def to_domain(self) -> Position:
        mark = None if self.marked_at is None else Mark(price=self.mark_price, at=self.marked_at)

        return Position(stock_id=self.stock_id, quantity=self.quantity, average_cost=self.average_cost, mark=mark)


class AccountSnapshotDTO(SQLModel, table=True):
    """Cash and positions right after the fill of `order_id`."""

    __tablename__: ClassVar[str] = "account_snapshots"

    snapshot_id: UUID = Field(primary_key=True)
    taken_at: datetime = Field(index=True, sa_type=UtcDateTime)
    run_id: UUID = Field(index=True)
    order_id: UUID = Field(index=True)
    cash: float
    positions: list[dict[str, Any]] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))

    @classmethod
    def from_domain(cls, snapshot: AccountSnapshot) -> Self:
        positions = [SnapshotPositionJson.from_domain(position).model_dump(mode="json") for position in snapshot.account.positions]

        return cls(
            snapshot_id=snapshot.snapshot_id,
            taken_at=snapshot.taken_at,
            run_id=snapshot.run_id,
            order_id=snapshot.order_id,
            cash=snapshot.account.cash,
            positions=positions,
        )

    def to_domain(self) -> AccountSnapshot:
        """The account id and opening times are not stored, so the account reads back with the defaults."""
        positions = [SnapshotPositionJson.model_validate(item).to_domain() for item in self.positions]

        return AccountSnapshot(
            snapshot_id=self.snapshot_id,
            taken_at=self.taken_at,
            run_id=RunId(self.run_id),
            order_id=OrderId(self.order_id),
            account=Account(cash=self.cash, positions=positions),
        )


class StockReportJson(BaseModel):
    """
    The `report` column of run_stock_reports, in the shape it has always stored: what a specific-stock analysis
    concluded about one stock, read from the Stock's attributes. It keeps the latest price and its time, never the
    daily history or the articles.
    """

    model_config = ConfigDict(from_attributes=True)

    stock_id: str
    name: str | None
    current_price: float | None
    latest_market_data_at: datetime | None
    technical_report: TechnicalReport | None
    ai_report: AiAnalysisReport | None
    composite_score: int | None


class RunStockReportDTO(SQLModel, table=True):
    """One stock of a specific-stock analysis, as its report, under its run, at its requested position."""

    __tablename__: ClassVar[str] = "run_stock_reports"

    run_id: UUID = Field(primary_key=True)
    position: int = Field(primary_key=True)
    stock_id: str
    report: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))

    @classmethod
    def from_domain(cls, run_id: RunId, position: int, stock: Stock) -> Self:
        report = StockReportJson.model_validate(stock).model_dump(mode="json")

        return cls(run_id=run_id, position=position, stock_id=stock.stock_id, report=report)

    def to_domain(self) -> Stock:
        """
        The stock as the run concluded about it. The saved price comes back as a one-bar daily history at its time, so
        current_price and latest_market_data_at read as saved; the market, the history and the articles are not kept.
        """
        report = StockReportJson.model_validate(self.report)
        price, at = report.current_price, report.latest_market_data_at
        latest = [] if price is None or at is None else [Ohlcv(ts=at, open=price, high=price, low=price, close=price)]

        return Stock(
            stock_id=report.stock_id,
            name=report.name,
            ohlcv=latest,
            technical_report=report.technical_report,
            ai_report=report.ai_report,
            composite_score=report.composite_score,
        )
