# backend/src/a_domain/types/enums.py

from enum import StrEnum, auto


class AiProvider(StrEnum):
    OPENAI = auto()
    GROK = auto()
    GEMINI = auto()
    GROQ = auto()


# TODO:
# Mihgt needa change name
class AiAnalysisFocus(StrEnum):
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


# TODO: Rethink about it.
class SignalSource(StrEnum):
    TECHNICAL = auto()
    COMBINED = auto()
    MANUAL = auto()


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
    MANUAL = auto()  # TODO: CLI For specific stock


class SystemEnvironment(StrEnum):
    DEV = auto()
    TEST = auto()
    LIVE = auto()


class ExecutionProvider(StrEnum):
    MOCK = auto()
    SHIOAJI = auto()


class OrderMode(StrEnum):
    MOCK_ONLY = auto()
    LIVE = auto()
    DISABLED = auto()


class RuleEffect(StrEnum):
    BLOCK_ON_FAIL = auto()
    REDUCE_SCORE_ON_FAIL = auto()
    INCREASE_SCORE_ON_PASS = auto()


# TODO: Do i really need it?
class TechnicalCriterionType(StrEnum):
    RSI_RANGE = auto()
    MFI_THRESHOLD = auto()
    MACD_BULLISH = auto()
    STOCHASTIC_HEALTH = auto()

    ADX_TREND = auto()
    GOLDEN_CROSS = auto()
    MA_ALIGNMENT = auto()
    PRICE_ABOVE_MA = auto()

    ATR_RANGE = auto()
    BOLLINGER_POSITION = auto()
    BOLLINGER_SQUEEZE = auto()
    BOLLINGER_THRESHOLD = auto()
    DAILY_RANGE = auto()

    LIQUIDITY = auto()
    MINIMUM_PRICE = auto()
    OBV_TREND = auto()
    VOLUME_EXPANSION = auto()
