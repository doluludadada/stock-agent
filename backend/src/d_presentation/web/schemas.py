"""
Request and response bodies of the Web API.

A route answers with the domain model itself when a client may see all of it. A response here holds only what a model
lacks or must hide. It maps a domain object field by field (from_attributes) and computes nothing: scores,
thresholds, eligibility and run counters come from the use cases that produced them.
"""

import re
from datetime import date, datetime
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, PositiveInt, SecretStr, StringConstraints

from a_domain.model.analysis.technical_report import TechnicalReport
from a_domain.model.fundamentals.eps import EpsUnavailable
from a_domain.model.fundamentals.monthly_revenue import MonthlyRevenue
from a_domain.model.fundamentals.quarter_financials import QuarterFinancials
from a_domain.model.market.ohlcv import Ohlcv
from a_domain.model.trading.account import AccountOpening
from a_domain.model.trading.order import Order
from a_domain.model.valuation.scan import ScanCriteria
from a_domain.model.valuation.valuation import PeMedian, ReportSection
from a_domain.ports.system.settings_files import SettingChange, SettingsProblem
from a_domain.rules.technical.strategy import TechnicalSettings, TechnicalStrategy
from a_domain.types.enums import (
    AiProvider,
    Audience,
    EliminationReason,
    EpsBasis,
    EpsKind,
    ErrorCode,
    ExecutionProvider,
    FollowRefusal,
    IndicatorOutput,
    InformationSource,
    MarketIndex,
    MarketType,
    OrderPricing,
    PeNotApplicableReason,
    Role,
    ScanStep,
    ScenarioName,
    SignalSource,
    TradeAction,
    UserStatus,
    WatchlistType,
    Workflow,
)
from a_domain.types.values import EmailAddress, NewPassword, PositiveFiniteFloat, Username

StockId = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=10, pattern=r"^[0-9A-Za-z]+$")]

REDACTIONS = (
    (re.compile(r"(?i)\b(bearer|token|api[_-]?key|secret|password)(\s*[:=]\s*|\s+)[^\s,;]+"), r"\1\2[redacted]"),
    (re.compile(r"(?i)([?&][\w-]*(?:key|token|secret|sig)[\w-]*=)[^&\s]+"), r"\1[redacted]"),
    (re.compile(r"\b(?:sk|xai|gsk|nvapi|tvly)-[A-Za-z0-9_-]{8,}"), "[redacted]"),
    (re.compile(r"(?:(?<=\s)|^|(?<=[('\"]))(?:/Users|/home|/root|/var|/opt|/private|/tmp|[A-Za-z]:\\)[^\s'\")]*"), "[path]"),
    (re.compile(r"\b[A-Z][12]\d{8}\b"), "[person id]"),
    (re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"), "[address]"),
    (
        re.compile(
            r"(?i)(?<![\w:])(?:(?:[0-9a-f]{1,4}:){7}[0-9a-f]{1,4}|(?:[0-9a-f]{1,4}:)+:(?:[0-9a-f]{1,4}(?::[0-9a-f]{1,4})*)?"
            r"|::[0-9a-f]{1,4}(?::[0-9a-f]{1,4})*)(?![\w:])"
        ),
        "[address]",
    ),
)


PUBLIC_TEXT_LIMIT = 600


def public_text(text: str) -> str:
    """
    A server message as a browser may see it: credentials, key-like query parameters, file system paths, Taiwan person
    ids and IP addresses are replaced, so an upstream error that quotes them leaks nothing, and a long one is cut. The
    full text stays in the server log.
    """
    for pattern, replacement in REDACTIONS:
        text = pattern.sub(replacement, text)

    return text if len(text) <= PUBLIC_TEXT_LIMIT else f"{text[:PUBLIC_TEXT_LIMIT]}…"


type PublicText = Annotated[str, AfterValidator(public_text)]


class Response(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------------------- #
#                                   Requests                                   #
# ---------------------------------------------------------------------------- #


class Confirmed(BaseModel):
    """Every write repeats the caller's confirmation in its body, so a stray or replayed request without it changes nothing."""

    confirm: Literal[True]


def each_once(stock_ids: list[str]) -> list[str]:
    """Each ID once, in the order given: a repeated ID is dropped before any lookup or AI call."""
    return list(dict.fromkeys(stock_ids))


type StockIdList = Annotated[list[StockId], Field(min_length=1, max_length=20), AfterValidator(each_once)]
"""At most 20 stock IDs per request: each analysed stock is one paid AI call."""


class StockIdsRequest(Confirmed):
    stock_ids: StockIdList


class TechnicalSettingsRequest(Confirmed):
    settings: TechnicalSettings
    """What GET /v1/technical-settings answered, edited, with the revision it carried. It is validated as a whole."""


# ---------------------------------------------------------------------------- #
#                                     Runs                                     #
# ---------------------------------------------------------------------------- #


class RunAccepted(BaseModel):
    run_id: UUID


class RunState(StrEnum):
    RUNNING = "running"
    """This server is running it now."""

    FINISHED = "finished"
    """It ran every step: its record has an end time and no failure. summary.errors lists what went wrong along the way."""

    FAILED = "failed"
    """
    It raised, or was cancelled at shutdown, and stopped; `error` says why, from its record. A run that stops before it
    is recorded (unreadable technical settings) has no summary, and a restart of the server that ran it forgets it.
    """

    UNFINISHED = "unfinished"
    """Its record has no end time and this server is not running it: another process runs it, or its process stopped."""


class RunSummary(Response):
    """The run record (SystemStats) the trading journal saved."""

    workflow: Workflow
    execution_provider: ExecutionProvider
    """The broker the run chose when it started: every order of the run went to it, or was refused."""

    start_time: datetime
    end_time: datetime | None
    followed_run_id: UUID | None = None
    """A follow's run: the run whose decisions it followed."""

    total_scanned: int
    buzz_scanned: int
    buzz_qualified: int
    passed_technical: int
    ai_analysed: int
    signals_generated: int
    orders_submitted: int
    orders_refused: int
    stale_market_data_count: int
    technical_strategy_id: str | None
    """The technical strategy the run applied, by its id; None for a run that applied none."""

    errors: list[PublicText]
    execution_log: list[PublicText]


class AiReportResponse(Response):
    score: int
    summary: str
    bullish_factors: list[str]
    bearish_factors: list[str]


class StockReportResponse(Response):
    """One requested stock after a specific-stock analysis (StockReport), as the CLI's Stock Reports table shows it."""

    stock_id: str
    name: str | None
    current_price: float | None
    latest_market_data_at: datetime | None
    technical_report: TechnicalReport | None
    ai_report: AiReportResponse | None
    composite_score: int | None


class RunResponse(BaseModel):
    run_id: UUID
    state: RunState
    error: PublicText | None = None
    summary: RunSummary | None
    """None until the run saves its first record."""

    reports: list[StockReportResponse] = Field(default_factory=list)
    """Specific-stock analysis only: the requested stocks' reports, saved with the run in the trading journal."""


class SignalResponse(Response):
    """A trading decision (TradeSignal) and its evidence; the AI report leaves out the model's raw answer."""

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
    technical_report: TechnicalReport | None
    ai_report: AiReportResponse | None
    followed_decision_id: UUID | None = None
    """A follow's decision: the decision of the followed run it carries out again."""


class FollowItem(BaseModel):
    """One follow of a decision: the follow's decision, priced when it was followed, and its order."""

    decision: SignalResponse
    order: Order


class FollowResponse(BaseModel):
    """What a follow of the run may take now, and what it took so far."""

    refusal: FollowRefusal | None
    """Why a follow may not start now; None when it may."""

    open_decision_ids: list[UUID]
    """
    The run's decisions still open to follow, at most one per stock. A decision is followed once a follow order of it
    filled since the mock account opened.
    """

    follows: list[FollowItem]
    """Every follow of the run's decisions so far, oldest first."""


# ---------------------------------------------------------------------------- #
#                                   Watchlist                                  #
# ---------------------------------------------------------------------------- #


class WatchlistEntryResponse(Response):
    stock_id: str
    name: str | None = None
    """The listing's name of the stock; None when the listing does not hold it any more."""

    watchlist_type: WatchlistType
    created_at: datetime
    expires_at: datetime | None
    """None: never expires (MANUAL)."""


class WatchlistAdditionResponse(Response):
    watchlist_type: WatchlistType
    added_stock_ids: list[str]
    already_present_stock_ids: list[str]


class WatchlistRemovalResponse(BaseModel):
    watchlist_type: Literal[WatchlistType.MANUAL] = WatchlistType.MANUAL
    removed_stock_ids: list[str]
    absent_stock_ids: list[str]
    """Requested stocks that had no MANUAL entry; their TECHNICAL or BUZZ entries, if any, are untouched."""


# ---------------------------------------------------------------------------- #
#                                    Account                                   #
# ---------------------------------------------------------------------------- #


class PositionValueResponse(Response):
    stock_id: str
    quantity: int
    average_cost: float
    mark_price: float
    marked_at: datetime | None
    """The time of the quote that prices the position. None: no price, valued at average cost."""

    market_value: float
    unrealized_pnl: float


class AccountValueResponse(Response):
    cash: float
    market_value: float
    unrealized_pnl: float
    equity: float
    positions: list[PositionValueResponse]


class RunReference(Response):
    """Which run a trade came from, as the account page names it."""

    run_id: UUID
    workflow: Workflow
    start_time: datetime


class TradeResponse(BaseModel):
    """An order that filled at least one share, and the run whose decision it carried out: the followed run for a follow."""

    order: Order
    run: RunReference


class ManualBuyRequest(Confirmed):
    """A manual BUY of one stock the specific-stock run reported, on the broker the request's `broker` query names."""

    stock_id: StockId
    quantity: PositiveInt
    """The shares to buy, at the realtime quote's price when the order is placed."""


class ResetRequest(Confirmed):
    initial_cash: PositiveFiniteFloat
    """The cash the mock account opens with again."""


class AccountAsOfResponse(BaseModel):
    last_fill_at: datetime
    value: AccountValueResponse


class AccountHistoryResponse(BaseModel):
    current: AccountValueResponse
    live_stock_ids: list[str]
    """The held stocks `current` prices at a live quote. Any other position is at its last daily close, or unpriced."""

    equity_curve: dict[date, AccountValueResponse]
    """The account at the end of each trading day since the first fill, in day order."""

    as_of: AccountAsOfResponse | None
    """None when as_of was not asked for, or no fill happened on or before it."""

    execution_provider: ExecutionProvider
    """Whose account this is: mock, the user's paper account in the app; shioaji, the SinoPac account of the site's login."""

    opening: AccountOpening | None
    """When the mock account opened, at its first read or its last reset, and the cash it opened with. None at a real broker."""

    profit: float | None
    """The account's equity now minus the cash it opened with. None at a real broker."""


class BrokerResponse(BaseModel):
    """
    A broker the signed-in user may choose for a run now, as a run's confirmation names it: the mock account always,
    SinoPac for an administrator while the site's login is up.
    """

    broker: ExecutionProvider
    simulation: bool | None
    """A real broker's server: true for SinoPac's simulation server (dev and test), false for the real account (prod)."""

    max_order_value: float | None
    """A real broker's most NT$ per BUY at its limit price (trading.max_order_value). None on the mock account."""

    max_daily_buy_value: float | None
    """A real broker's most NT$ of BUYs per Taiwan calendar day (trading.max_daily_buy_value). None on the mock account."""


# ---------------------------------------------------------------------------- #
#                                  Market data                                 #
# ---------------------------------------------------------------------------- #


class ListedStockResponse(Response):
    """A listed stock (Stock). `today` is its official bar of the listing's latest session; None when it did not trade."""

    stock_id: str
    name: str | None
    market: MarketType
    today: Ohlcv | None


class StockHistoryResponse(BaseModel):
    stock: ListedStockResponse
    """Its `today` is the latest completed daily bar of the history."""

    bars: list[Ohlcv]
    """Completed daily bars, oldest first. Empty when the history is unavailable or stale; `notes` says why."""

    notes: list[PublicText]


class IndexHistoryResponse(BaseModel):
    index: MarketIndex
    bars: list[Ohlcv]
    """
    Completed daily bars, oldest first, as the exchange's own monthly index reports give them on a personal site, with
    its market's volume in shares, else as the open-data archive keeps its close: such a bar's open, high and low are
    its close and its volume 0. Empty when none is in the window.
    """


class ArchiveStatusResponse(BaseModel):
    """
    The open-data archive's warm-up. A public site reads its daily history from the archive alone, so its runs find no
    candidate until `sessions` reaches `needed`.
    """

    sessions: int
    """The sessions of TWSE and TPEX stock closes the archive holds: the most daily bars it can serve one stock."""
    needed: int
    """The daily bars the built-in strategies need: the most any of them reads."""


class AudienceResponse(BaseModel):
    """
    Whom the site serves and what that allows, as the Audience table says, so the web app offers only what the site can
    do. The server still refuses the rest on every request.
    """

    audience: Audience
    open_data_only: bool
    """Daily history and the index trend come from the open-data archive alone: a run finds no candidate until it holds enough."""
    realtime_quotes: bool
    """
    Buzz, Intraday and the manual BUY, which order on realtime quotes: where the audience allows them and this runtime
    has a Shioaji login.
    """
    news_articles: bool
    """The news sites' articles and the AI's web search."""
    mops: bool
    """The valuation, which reads MOPS's income statements."""
    order_pricing: OrderPricing
    """
    What prices an order, a follow's included: a realtime quote in continuous trading, or the official close of the
    last closed session while no session trades, on the mock broker only.
    """


class StockFinancialsResponse(BaseModel):
    """
    A stock's financials as the server's open-data archive holds them. The OpenAPI serves only the latest quarter and
    month, so the archive holds those it saved while they were served, and nothing before the archive started.
    """

    stock_id: str
    quarters: list[QuarterFinancials]
    """Each archived quarter's figures, oldest first."""

    monthly_revenues: list[MonthlyRevenue]
    """Each archived month's revenue, oldest first."""


class StockTechnicalResponse(BaseModel):
    stock_id: str
    strategy: TechnicalStrategy
    """The owner's active strategy, as the evaluation applied it."""

    required_bars: int
    """The completed daily bars the strategy needs; a stock with fewer fails with score 0."""

    bar_times: list[datetime]
    """The session close of each bar the evaluation read, oldest first; `readings` follow this order."""

    latest_price: float | None
    """The price the rules read as the latest price: the last daily close, since the page fetches no realtime quote."""

    report: TechnicalReport | None
    readings: dict[str, list[dict[IndicatorOutput, float]]]
    """Each indicator's outputs at each bar; an output the history cannot give yet is absent from that bar."""

    notes: list[PublicText]


# ---------------------------------------------------------------------------- #
#                                   Valuation                                  #
# ---------------------------------------------------------------------------- #


class ExplanationRequest(Confirmed):
    """One AI call explains one stock's valuation; the numbers are the domain's, the AI writes only text."""

    stock_id: StockId
    target_pe: Annotated[float, Field(gt=0, le=1000, allow_inf_nan=False)]


class EpsResponse(Response):
    """An EPS figure (Eps): it never comes without its period, kind, basis, source and fetch time."""

    value: float
    kind: EpsKind
    period_label: str
    basis: EpsBasis
    source: InformationSource
    fetched_at: datetime


class PeRatioResponse(Response):
    price: float
    eps: float
    value: float


class ScenarioResponse(Response):
    name: ScenarioName
    target_pe: float
    assumption: str
    fair_price: float
    gap: float
    undervaluation: float


class FairPriceRangeResponse(Response):
    conservative: ScenarioResponse
    base: ScenarioResponse
    optimistic: ScenarioResponse


class ValuedStockResponse(Response):
    stock_id: str
    name: str | None
    industry: str | None


class StockValuationResponse(Response):
    """One stock's valuation before any user assumption (StockValuation)."""

    stock: ValuedStockResponse
    close: Ohlcv | None
    close_is_fresh: bool
    eps: EpsResponse | EpsUnavailable
    current_pe: PeRatioResponse | PeNotApplicableReason
    warnings: list[str]
    industry_median_pe: PeMedian | None
    """A reference only, never a target: the stock's industry's median P/E over stocks with a fresh close."""


class ValuationReportResponse(Response):
    """A stock valued at the user's target P/E (ValuationReport). Scenarios exist exactly when its P/E is computable."""

    valuation: StockValuationResponse
    target_pe: float | None
    fair_value: FairPriceRangeResponse | PeNotApplicableReason
    undervaluation: float | None


class ValuationReportsResponse(BaseModel):
    reports: list[ValuationReportResponse]


class MarketValuationResponse(BaseModel):
    last_closed_session: date
    valued_stocks: int
    median_pe: PeMedian | None
    source_warnings: list[PublicText]


class ValuationScanResponse(BaseModel):
    market: MarketValuationResponse
    criteria: ScanCriteria
    technical_strategy_id: str | None
    """None until the technical step ran; then the strategy it applied."""

    survivors: list[ValuationReportResponse]
    """Most undervalued first. A survivor is a stock to research, never a BUY."""

    technical_failures: dict[str, str]
    """Stocks the technical step eliminated, with the strategy's hard failures."""

    eliminated: dict[ScanStep, dict[EliminationReason, int]]
    explanation_candidates: list[str]
    """The stock ids the scan offers for an AI explanation, at most valuation.max_scan_explanations."""


class ValuationExplanationResponse(BaseModel):
    report: ValuationReportResponse
    sections: tuple[ReportSection, ...]


# ---------------------------------------------------------------------------- #
#                                Settings form                                 #
# ---------------------------------------------------------------------------- #


class SettingsSaveRequest(Confirmed):
    changes: Annotated[list[SettingChange], Field(max_length=300)]
    """
    The settings the form changes, each by its field's path, in order. A change to the value its field shows changes
    nothing.
    """

    password: Annotated[SecretStr, Field(max_length=256)] | None = None
    """The administrator's own password, which every save needs: without it, 403. Never logged or echoed."""


class ErrorResponse(BaseModel):
    """Every refusal: `detail` in words for a person, `code` for the client to switch on."""

    detail: str
    code: ErrorCode


class ProblemsResponse(ErrorResponse):
    """Settings the app would not start with (`settings_refused`): nothing was saved; the problems say where and why."""

    problems: list[SettingsProblem]


class AuthStatusResponse(BaseModel):
    """What the web app shows first: the first-time setup, or sign-in with or without registration."""

    needs_first_administrator: bool
    registration_open: bool


class RegistrationRequest(BaseModel):
    username: Username
    email: EmailAddress
    password: NewPassword


class SetupRequest(RegistrationRequest):
    """The first administrator, with the one-time code the server printed on its console at start."""

    setup_code: SecretStr


class SignInRequest(BaseModel):
    identifier: Annotated[str, StringConstraints(min_length=1, max_length=254)]
    """A username or an email, in any case."""
    password: Annotated[SecretStr, Field(max_length=256)]


class UserChangeRequest(Confirmed):
    """An administrator's change of one user. A field left out stays as it is."""

    role: Role | None = None
    status: UserStatus | None = None
    password: NewPassword | None = None


class AiModelResponse(BaseModel):
    """My settings' AI model: the models the site offers its users, its default among them, and the one the user's runs use."""

    models: dict[AiProvider, str]
    """Each AI model the site offers, by provider, with its model id: the site's default first, then ai.user_selectable."""
    site_default: AiProvider
    in_use: AiProvider
    """The user's choice while the site offers it, else the site's default: a choice the site stopped offering falls back."""


class AiModelRequest(Confirmed):
    ai_model: AiProvider | None
    """One of the offered models, or null for the site's default, which follows the administrator's later changes."""
