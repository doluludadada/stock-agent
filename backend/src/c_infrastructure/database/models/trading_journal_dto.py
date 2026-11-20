from datetime import date, datetime
from typing import Any, ClassVar, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, field_validator
from sqlalchemy import JSON, Column, Index
from sqlmodel import Field, SQLModel

from a_domain.model.analysis.ai_analysis_report import AiAnalysisReport
from a_domain.model.analysis.technical_report import TechnicalReport
from a_domain.model.market.ohlcv import Ohlcv
from a_domain.model.market.stock import Stock
from a_domain.model.trading.account import Account, AccountSnapshot, Mark, Position
from a_domain.model.trading.signal import TradeSignal
from a_domain.types.enums import ExecutionProvider, OrderStatus, OrderType, SignalSource, TimeInForce, TradeAction, Workflow
from a_domain.types.ids import OrderId, RunId
from c_infrastructure.database.utc_datetime import UtcDateTime


def stored_technical_report(report: dict[str, Any] | None) -> dict[str, Any] | None:
    """
    A report as TechnicalReport reads it. A row written before an observation was an item holds each one as the
    sentence `<rule>: detected` or `<rule>: not detected`, which says the same two things.
    """
    if report is None:
        return None

    observations = [
        {"rule": item.rpartition(": ")[0], "detected": item.endswith(": detected")} if isinstance(item, str) else item
        for item in report.get("observations", [])
    ]

    return {**report, "observations": observations}


class WorkflowRunDTO(SQLModel, table=True):
    """One workflow run (SystemStats) of one owner. end_time stays empty when the run never finished."""

    __tablename__: ClassVar[str] = "workflow_runs"
    __table_args__ = (Index("ix_workflow_runs_owner_start", "owner_id", "start_time"),)

    run_id: UUID = Field(primary_key=True)
    workflow: Workflow
    execution_provider: ExecutionProvider
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
    owner_id: str = Field(exclude=True)
    """
    The user the run belongs to. Every owned table ended with this column, as the upgrade to version 3 added it. It never
    leaves the row: model_dump(), which reads the row back into its domain model, leaves it out.
    """

    followed_run_id: UUID | None = None
    """A follow's run: the run whose decisions it followed. After the owner, as the upgrade to version 5 added it."""

    ranking_formula: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON, nullable=True))
    """A ranking follow's formula (RankingFormula) as it was defined then, as the upgrade to version 10 added it."""

    ranking_decided_on: date | None = None
    scheduled: bool = False
    """The decision a ranking follow took, and whether the schedule started the run, as the upgrade to version 11 added them."""

    ranking_open: int | None = None
    """How many stocks a ranking follow still had to trade at its last look. Last, as the upgrade to version 12 added it."""


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
    owner_id: str = Field(exclude=True)
    followed_decision_id: UUID | None = None
    """A follow's decision: the decision of another run it follows. Last, as the upgrade to version 5 added it."""

    def to_domain(self) -> TradeSignal:
        row = self.model_dump(exclude={"run_id"})

        return TradeSignal(**{**row, "technical_report": stored_technical_report(self.technical_report)})


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
    owner_id: str = Field(exclude=True)
    price_at_signal: float
    """The price the order's decision saw. Last, as the upgrade to version 16 added it."""


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
    """One owner's cash and positions right after the fill of `order_id`."""

    __tablename__: ClassVar[str] = "account_snapshots"
    __table_args__ = (Index("ix_account_snapshots_owner_taken", "owner_id", "taken_at"),)

    snapshot_id: UUID = Field(primary_key=True)
    taken_at: datetime = Field(index=True, sa_type=UtcDateTime)
    run_id: UUID = Field(index=True)
    order_id: UUID = Field(index=True)
    cash: float
    positions: list[dict[str, Any]] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    owner_id: str

    @classmethod
    def from_domain(cls, snapshot: AccountSnapshot, owner_id: str) -> Self:
        positions = [SnapshotPositionJson.from_domain(position).model_dump(mode="json") for position in snapshot.account.positions]

        return cls(
            snapshot_id=snapshot.snapshot_id,
            taken_at=snapshot.taken_at,
            run_id=snapshot.run_id,
            order_id=snapshot.order_id,
            cash=snapshot.account.cash,
            positions=positions,
            owner_id=owner_id,
        )

    def to_domain(self) -> AccountSnapshot:
        """The account is the owner's, whose id is its account id. Opening times are not stored, so they read back empty."""
        positions = [SnapshotPositionJson.model_validate(item).to_domain() for item in self.positions]

        return AccountSnapshot(
            snapshot_id=self.snapshot_id,
            taken_at=self.taken_at,
            run_id=RunId(self.run_id),
            order_id=OrderId(self.order_id),
            account=Account(account_id=self.owner_id, cash=self.cash, positions=positions),
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

    @field_validator("technical_report", mode="before")
    @classmethod
    def reads_a_stored_report(cls, report: object) -> object:
        return stored_technical_report(report) if isinstance(report, dict) else report


class RunStockReportDTO(SQLModel, table=True):
    """One stock of a specific-stock analysis, as its report, under its run, at its requested position."""

    __tablename__: ClassVar[str] = "run_stock_reports"

    run_id: UUID = Field(primary_key=True)
    position: int = Field(primary_key=True)
    stock_id: str
    report: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))
    owner_id: str

    @classmethod
    def from_domain(cls, run_id: RunId, position: int, stock: Stock, owner_id: str) -> Self:
        report = StockReportJson.model_validate(stock).model_dump(mode="json")

        return cls(run_id=run_id, position=position, stock_id=stock.stock_id, report=report, owner_id=owner_id)

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
