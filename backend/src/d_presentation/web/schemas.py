"""
Request and response bodies of the Web API.

Every response maps a domain object field by field (from_attributes) and computes nothing: scores, thresholds,
eligibility and run counters come from the use cases that produced them.
"""

from datetime import date, datetime
from enum import StrEnum
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from a_domain.types.enums import (
    ExecutionProvider,
    OrderMode,
    OrderStatus,
    OrderType,
    SignalSource,
    TimeInForce,
    TradeAction,
    WatchlistType,
    Workflow,
)

StockId = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class Response(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------------------- #
#                                   Requests                                   #
# ---------------------------------------------------------------------------- #


class Confirmed(BaseModel):
    """Every write repeats the caller's confirmation in its body, so a stray or replayed request without it changes nothing."""

    confirm: Literal[True]


class StockIdsRequest(Confirmed):
    stock_ids: list[StockId] = Field(min_length=1)


class TechnicalSettingsRequest(Confirmed):
    settings: dict[str, Any]
    """The document GET /v1/technical-settings returns, edited. The server validates it as a whole."""


# ---------------------------------------------------------------------------- #
#                                     Runs                                     #
# ---------------------------------------------------------------------------- #


class RunAccepted(BaseModel):
    run_id: UUID


class RunState(StrEnum):
    RUNNING = "running"
    """This server is running it now."""

    FINISHED = "finished"
    """It ended: its record has an end time. summary.errors lists what went wrong along the way."""

    FAILED = "failed"
    """
    It raised while this server ran it; `error` says why. A run that stops before it is recorded (unreadable technical
    settings) has no summary.
    """

    UNFINISHED = "unfinished"
    """Its record has no end time and this server is not running it: another process runs it, or its process stopped."""


class RunSummary(Response):
    """The run record (SystemStats) the trading journal saved."""

    workflow: Workflow
    execution_provider: ExecutionProvider
    order_mode: OrderMode
    start_time: datetime
    end_time: datetime | None
    total_scanned: int
    buzz_scanned: int
    buzz_qualified: int
    passed_technical: int
    ai_analysed: int
    signals_generated: int
    orders_submitted: int
    orders_refused: int
    stale_market_data_count: int
    errors: list[str]
    execution_log: list[str]


class TechnicalReportResponse(Response):
    score: int
    hard_failures: list[str]
    soft_failures: list[str]
    observations: list[str]


class AiReportResponse(Response):
    score: int
    summary: str
    bullish_factors: list[str]
    bearish_factors: list[str]


class StockReportResponse(Response):
    """One requested stock after a specific-stock analysis, as the CLI's Stock Reports table shows it."""

    stock_id: str
    name: str | None
    current_price: float | None
    latest_market_data_at: datetime | None
    technical_report: TechnicalReportResponse | None
    ai_report: AiReportResponse | None
    composite_score: int | None


class RunResponse(BaseModel):
    run_id: UUID
    state: RunState
    error: str | None = None
    summary: RunSummary | None
    """None until the run saves its first record."""

    reports: list[StockReportResponse] = Field(default_factory=list)
    """
    Specific-stock analysis only: the requested stocks' reports. The journal does not store them, so they last while
    this server runs.
    """


class SignalResponse(Response):
    run_id: UUID
    decision_id: UUID
    stock_id: str
    action: TradeAction
    source: SignalSource
    score: int
    reason: str
    quantity: int
    stop_loss_price: float | None
    generated_at: datetime
    price_at_signal: float
    price_observed_at: datetime
    history_until: datetime | None
    technical_report: TechnicalReportResponse | None
    ai_report: AiReportResponse | None


class OrderResponse(Response):
    id: UUID
    run_id: UUID
    decision_id: UUID
    stock_id: str
    action: TradeAction
    order_type: OrderType
    quantity: int
    limit_price: float | None
    time_in_force: TimeInForce
    status: OrderStatus
    reason: str | None
    filled_quantity: int
    average_filled_price: float | None
    fee: int
    tax: int
    realized_pnl: float | None
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------- #
#                                   Watchlist                                  #
# ---------------------------------------------------------------------------- #


class WatchlistEntryResponse(Response):
    stock_id: str
    watchlist_type: WatchlistType
    created_at: datetime
    expires_at: datetime | None
    """None: never expires (MANUAL)."""


class WatchlistAdditionResponse(Response):
    watchlist_type: WatchlistType
    added_stock_ids: list[str]
    already_present_stock_ids: list[str]


# ---------------------------------------------------------------------------- #
#                                    Account                                   #
# ---------------------------------------------------------------------------- #


class PositionResponse(Response):
    stock_id: str
    quantity: int
    average_cost: float


class MarkResponse(Response):
    ts: datetime
    close: float


class PositionValuationResponse(Response):
    position: PositionResponse
    mark: MarkResponse | None
    """The quote that prices the position. None: no price, valued at average cost."""

    market_value: float
    unrealized_pnl: float


class AccountValuationResponse(Response):
    cash: float
    market_value: float
    unrealized_pnl: float
    equity: float
    positions: list[PositionValuationResponse]


class EquityPointResponse(Response):
    day: date
    cash: float
    market_value: float
    equity: float


class AccountAsOfResponse(BaseModel):
    last_fill_at: datetime
    valuation: AccountValuationResponse


class AccountHistoryResponse(BaseModel):
    current: AccountValuationResponse
    live_stock_ids: list[str]
    """The held stocks `current` prices at a live quote. Any other position is at its last daily close, or unpriced."""

    equity_curve: list[EquityPointResponse]
    as_of: AccountAsOfResponse | None
    """None when as_of was not asked for, or no fill happened on or before it."""
