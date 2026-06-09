from enum import StrEnum, auto


class AiProvider(StrEnum):
    OPENAI = auto()
    GROK = auto()
    GEMINI = auto()
    GROQ = auto()


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
    TECHNICAL = auto()
    FUNDAMENTAL = auto()
    HYBRID = auto()


class OrderType(StrEnum):
    MARKET = auto()
    LIMIT = auto()


class OrderStatus(StrEnum):
    PENDING = auto()
    SUBMITTED = auto()
    FILLED = auto()
    CANCELLED = auto()
    FAILED = auto()
    REJECTED = auto()


class TimeInForce(StrEnum):
    ROD = auto()
    IOC = auto()
    FOK = auto()


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


# TODO: Rename it
class WatchlistType(StrEnum):
    TECHNICAL = auto()
    BUZZ = auto()
    TECHNICAL_AND_BUZZ = auto()
    MANUAL = auto()
    HELD_POSITION = auto() #

# TODO: What do i do for it?
class MarketDataMode(StrEnum):
    LIVE = auto()
    LATEST_COMPLETED_SESSION = auto()

# TODO: Do i need it?
class AnalysisStage(StrEnum):
    PENDING = auto()
    DATA_COLLECTED = auto()
    FILTERED_PASS = auto()
    FILTERED_FAIL = auto()
    ENRICHED = auto()
    ANALYZED = auto()
    DECIDED = auto()


class SystemEnvironment(StrEnum):
    DEV = auto()
    TEST = auto()
    LIVE = auto()


class StrategyName(StrEnum):
    CONSERVATIVE = auto()
    MODERATE = auto()
    AGGRESSIVE = auto()
    BUZZ = auto()
    NIGHTLY = auto()
