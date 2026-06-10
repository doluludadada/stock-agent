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


# TODO: Rethink about it.
class SignalSource(StrEnum):
    TECHNICAL = auto()
    COMBINED = auto()


class OrderType(StrEnum):
    MARKET = auto()
    LIMIT = auto()  # TODO: it should be used.


# TODO: Needa wire it up
class OrderStatus(StrEnum):
    PENDING = auto()
    SUBMITTED = auto()
    FILLED = auto()
    CANCELLED = auto()
    FAILED = auto()
    REJECTED = auto()


# TODO: Needa wire it up
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


class WatchlistType(StrEnum):
    TECHNICAL = auto()  # TODO: technical_filter.py should use it
    BUZZ = auto()
    TECHNICAL_AND_BUZZ = auto()  # TODO: signals.py should use it
    MANUAL = auto()  # TODO: CLI For specific stock


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
