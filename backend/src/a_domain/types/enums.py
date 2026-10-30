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


class DatabaseProvider(StrEnum):
    MEMORY = auto()
    CHROMA = auto()


class MarketType(StrEnum):
    TWSE = auto()
    TPEX = auto()
    NASDAQ = auto()
    NYSE = auto()


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


class TimeInForce(StrEnum):
    """How long an accepted order keeps working (Taiwan exchange terms)."""

    ROD = auto()
    """Rest of Day: the unfilled part keeps working until the session closes."""

    IOC = auto()
    """Immediate or Cancel: fill what is available now, cancel the rest. What OrderExecution sends."""

    FOK = auto()
    """Fill or Kill: fill the whole quantity now or cancel all of it."""


class InformationSource(StrEnum):
    TWSE_MOPS = auto()
    NEWS_MEDIA = auto()
    PTT_STOCK = auto()
    PTT_GOSSIPING = auto()
    REUNION = auto()


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
