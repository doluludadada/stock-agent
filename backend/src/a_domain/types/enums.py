# backend/src/a_domain/types/enums.py

from enum import StrEnum, auto


class AiProvider(StrEnum):
    OPENAI = auto()
    GROK = auto()
    GEMINI = auto()
    GROQ = auto()


class AiAnalysisFocus(StrEnum):
    """Which prompt the AI analysis uses: company fundamentals (full cycle, intraday) or short-term momentum (buzz)."""

    FUNDAMENTAL = auto()
    MOMENTUM = auto()


class MessageRole(StrEnum):
    SYSTEM = auto()
    USER = auto()
    ASSISTANT = auto()


class MarketType(StrEnum):
    TWSE = auto()
    TPEX = auto()


class SecurityKind(StrEnum):
    """What a listed code trades as. Tick sizes and the SELL transaction tax differ by kind."""

    STOCK = auto()

    ETF = auto()
    """Exchange-traded fund. Taiwan ETF codes start with 00: 0050, 00878, 006208."""

    BOND_ETF = auto()
    """An ETF that holds bonds: a 00 code ending in B, such as 00679B. It trades on the ETF tick grid."""

    @classmethod
    def of(cls, stock_id: str) -> SecurityKind:
        if not stock_id.startswith("00"):
            return cls.STOCK

        return cls.BOND_ETF if stock_id.endswith("B") else cls.ETF


class TradeAction(StrEnum):
    BUY = auto()
    SELL = auto()
    HOLD = auto()


class SignalSource(StrEnum):
    """Which decision path produced a signal."""

    COMBINED = auto()
    """DecisionRule on the composite technical + AI score (EntryRule BUY/ADD, ExitRule score SELL)."""

    STOP_LOSS = auto()
    """ExitRule stop-loss: the price fell to the stop below the position's average cost."""

    MANUAL = auto()
    """The user confirmed a manual BUY override."""


class OrderType(StrEnum):
    MARKET = auto()
    """Executes at whatever price the market gives. OrderExecution never sends it; the mock rejects it."""

    LIMIT = auto()
    """Executes at the limit price or better. OrderExecution prices every order at its signal's fresh quote."""


class OrderStatus(StrEnum):
    """Order lifecycle. Legal changes are listed once, in a_domain.model.trading.order.ORDER_TRANSITIONS."""

    PENDING = auto()
    SUBMITTED = auto()
    FILLED = auto()
    CANCELLED = auto()
    FAILED = auto()
    REJECTED = auto()


class RejectReason(StrEnum):
    """Why an order was REJECTED before acceptance: by the app's order gate or by the broker's pre-trade checks."""

    ORDER_MODE_DISABLED = auto()
    ORDER_MODE_MISMATCH = auto()
    MARKET_CLOSED = auto()
    STALE_PRICE = auto()
    INSUFFICIENT_CASH = auto()
    POSITION_NOT_FOUND = auto()
    INSUFFICIENT_POSITION = auto()
    UNSUPPORTED_ORDER_TYPE = auto()
    UNSUPPORTED_TIME_IN_FORCE = auto()
    BROKER_REFUSED = auto()
    """The real broker refused the order before it worked (its own checks or the exchange's); the detail quotes the broker."""


class TradingPhase(StrEnum):
    """Where the exchange's trading day stands. Only CONTINUOUS trading takes the IOC orders the app sends."""

    CLOSED = auto()

    OPENING_AUCTION = auto()
    """Orders queue for the opening call auction, which takes limit ROD orders only."""

    CONTINUOUS = auto()
    """Continuous trading: limit and market orders, ROD, IOC and FOK."""

    CLOSING_AUCTION = auto()
    """Orders queue for the closing call auction, which takes limit ROD orders only."""


class TimeInForce(StrEnum):
    """How long an accepted order keeps working (Taiwan exchange terms)."""

    ROD = auto()
    """Rest of Day: the unfilled part keeps working until the session closes."""

    IOC = auto()
    """Immediate or Cancel: fill what is available now, cancel the rest. What OrderExecution sends."""

    FOK = auto()
    """Fill or Kill: fill the whole quantity now or cancel all of it."""


class LotKind(StrEnum):
    """How the exchange counts an order's quantity. A broker sends each kind as its own exchange order."""

    BOARD_LOT = auto()
    """Whole board lots (market.board_lot_shares shares each), traded on the regular board."""

    ODD_LOT = auto()
    """Fewer shares than one board lot, traded on the intraday odd-lot board."""


class InformationSource(StrEnum):
    TWSE_MOPS = auto()
    NEWS_MEDIA = auto()
    PTT_STOCK = auto()
    PTT_GOSSIPING = auto()
    REUNION = auto()

    @property
    def is_social(self) -> bool:
        """Public discussion boards, as opposed to news media and company filings."""
        return self in {InformationSource.PTT_STOCK, InformationSource.PTT_GOSSIPING}


class SentimentLabel(StrEnum):
    """One post's stance toward its stock."""

    BULLISH = auto()
    BEARISH = auto()
    NEUTRAL = auto()
    UNCLEAR = auto()


class SentimentConsensus(StrEnum):
    """What a stock's posts say together. DISAGREEMENT is its own state and never folds into NEUTRAL."""

    BULLISH = auto()
    BEARISH = auto()
    NEUTRAL = auto()
    DISAGREEMENT = auto()
    UNCLEAR = auto()


class ContentType(StrEnum):
    FACT = auto()
    NEWS = auto()
    REPORT = auto()
    ANALYSIS = auto()
    DISCUSSION = auto()
    NOISE = auto()


class WatchlistType(StrEnum):
    TECHNICAL = auto()
    BUZZ = auto()
    MANUAL = auto()


class SystemEnvironment(StrEnum):
    DEV = auto()
    TEST = auto()
    LIVE = auto()


class ExecutionProvider(StrEnum):
    MOCK = auto()
    SHIOAJI = auto()


class Workflow(StrEnum):
    """The user-facing operation a run belongs to. Each run has one run id."""

    FULL_CYCLE = auto()
    BUZZ_SCAN = auto()
    INTRADAY = auto()
    SPECIFIC_STOCKS = auto()
    MANUAL_BUY = auto()
    VALUATION = auto()
    """Menus 5 and 6. Read-only: no run record, no order."""


class OrderMode(StrEnum):
    MOCK_ONLY = auto()
    LIVE = auto()
    DISABLED = auto()


class RuleEffect(StrEnum):
    BLOCK_ON_FAIL = auto()
    REDUCE_SCORE_ON_FAIL = auto()
    INCREASE_SCORE_ON_PASS = auto()


class EpsKind(StrEnum):
    SINGLE_QUARTER = auto()
    CUMULATIVE = auto()
    ANNUAL = auto()
    TRAILING_TWELVE_MONTHS = auto()

    @property
    def label(self) -> str:
        return EPS_KIND_LABELS[self]


EPS_KIND_LABELS = {
    EpsKind.SINGLE_QUARTER: "single quarter",
    EpsKind.CUMULATIVE: "cumulative",
    EpsKind.ANNUAL: "annual",
    EpsKind.TRAILING_TWELVE_MONTHS: "TTM",
}


class EpsBasis(StrEnum):
    ACTUAL = auto()
    ESTIMATE = auto()

    @property
    def label(self) -> str:
        return "actual" if self == EpsBasis.ACTUAL else "estimate"


class EpsUnavailableReason(StrEnum):
    NOT_LOADED = auto()
    """The workflow did not load fundamentals for this stock."""

    NOT_REPORTED = auto()
    """No filing in any candidate quarter: an ETF, a DR, a new listing or a suspended filer."""

    INCOMPLETE_HISTORY = auto()
    """The TTM needs a prior-year filing the company does not have."""

    SOURCE_FAILED = auto()
    """A quarter the TTM needs could not be fetched."""


class ScanStep(StrEnum):
    VALUATION = auto()
    TECHNICAL = auto()

    @property
    def label(self) -> str:
        return "valuation" if self == ScanStep.VALUATION else "technical"


class EliminationReason(StrEnum):
    EPS_UNAVAILABLE = auto()
    EPS_NOT_POSITIVE = auto()
    PRICE_MISSING = auto()
    PRICE_STALE = auto()
    BELOW_MIN_UNDERVALUATION = auto()
    NO_PRICE_HISTORY = auto()
    TECHNICAL_HARD_FAILURE = auto()

    @property
    def step(self) -> ScanStep:
        if self in (EliminationReason.NO_PRICE_HISTORY, EliminationReason.TECHNICAL_HARD_FAILURE):
            return ScanStep.TECHNICAL

        return ScanStep.VALUATION

    @property
    def label(self) -> str:
        return ELIMINATION_LABELS[self]


ELIMINATION_LABELS = {
    EliminationReason.EPS_UNAVAILABLE: "insufficient EPS data",
    EliminationReason.EPS_NOT_POSITIVE: "EPS ≤ 0",
    EliminationReason.PRICE_MISSING: "no valid price",
    EliminationReason.PRICE_STALE: "stale price",
    EliminationReason.BELOW_MIN_UNDERVALUATION: "undervaluation below the minimum",
    EliminationReason.NO_PRICE_HISTORY: "no usable daily history (missing or stale), so the technical strategy cannot run",
    EliminationReason.TECHNICAL_HARD_FAILURE: "technical hard failure",
}


class PeNotApplicableReason(StrEnum):
    EPS_UNAVAILABLE = auto()
    EPS_ZERO = auto()
    EPS_NEGATIVE = auto()
    INVALID_PRICE = auto()

    @property
    def label(self) -> str:
        return PE_NOT_APPLICABLE_LABELS[self]


PE_NOT_APPLICABLE_LABELS = {
    PeNotApplicableReason.EPS_UNAVAILABLE: "insufficient data",
    PeNotApplicableReason.EPS_ZERO: "cannot be computed",
    PeNotApplicableReason.EPS_NEGATIVE: "loss-making, P/E not applicable",
    PeNotApplicableReason.INVALID_PRICE: "no valid price",
}


class ScenarioName(StrEnum):
    CONSERVATIVE = auto()
    BASE = auto()
    OPTIMISTIC = auto()

    @property
    def label(self) -> str:
        return {ScenarioName.CONSERVATIVE: "Conservative", ScenarioName.BASE: "Base", ScenarioName.OPTIMISTIC: "Optimistic"}[self]
