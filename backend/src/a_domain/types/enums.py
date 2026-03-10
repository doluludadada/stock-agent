from enum import StrEnum


class MessageRole(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class AiProvider(StrEnum):
    OPENAI = "openai"
    GROK = "grok"
    GEMINI = "gemini"
    GROQ = "groq"


class DatabaseProvider(StrEnum):
    MEMORY = "memory"
    CHROMA = "chroma"


class MarketType(StrEnum):
    TWSE = "TWSE"
    TPEX = "TPEX"
    NASDAQ = "NASDAQ"
    NYSE = "NYSE"


class MaPeriod(StrEnum):
    MA_5 = "MA_5"
    MA_10 = "MA_10"
    MA_20 = "MA_20"
    MA_60 = "MA_60"
    MA_120 = "MA_120"


class SignalAction(StrEnum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


class SignalSource(StrEnum):
    TECHNICAL = "TECHNICAL"
    FUNDAMENTAL = "FUNDAMENTAL"
    HYBRID = "HYBRID"


class OrderType(StrEnum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"


class OrderAction(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


class OrderStatus(StrEnum):
    PENDING = "PENDING"
    SUBMITTED = "SUBMITTED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"


class TimeInForce(StrEnum):
    ROD = "ROD"
    IOC = "IOC"
    FOK = "FOK"


class InformationSource(StrEnum):
    TWSE_MOPS = "TWSE_MOPS"
    NEWS_MEDIA = "NEWS_MEDIA"
    PTT_STOCK = "PTT_STOCK"
    PTT_GOSSIPING = "PTT_GOSSIPING"
    REUNION = "REUNION"


class ContentType(StrEnum):
    FACT = "FACT"
    REPORT = "REPORT"
    ANALYSIS = "ANALYSIS"
    DISCUSSION = "DISCUSSION"
    NOISE = "NOISE"


class SentimentType(StrEnum):
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    NEUTRAL = "NEUTRAL"


class CandidateSource(StrEnum):
    TECHNICAL_WATCHLIST = "TECHNICAL_WATCHLIST"
    SOCIAL_BUZZ = "SOCIAL_BUZZ"
    MANUAL_INPUT = "MANUAL_INPUT"


class AnalysisStage(StrEnum):
    PENDING = "PENDING"
    DATA_COLLECTED = "DATA_COLLECTED"
    FILTERED_PASS = "FILTERED_PASS"
    FILTERED_FAIL = "FILTERED_FAIL"
    ENRICHED = "ENRICHED"
    ANALYZED = "ANALYZED"
    DECIDED = "DECIDED"

class SystemEnvironment(StrEnum):
    DEV = "dev"   # Logs only, mock returns
    TEST = "test" # Paper trading (SQLite)
    LIVE = "live" # Real execution (Shioaji)


class SignalReason(StrEnum):
    NIGHTLY_SCREEN = "Nightly Technical Scan"
    SOCIAL_BUZZ    = "Social Media Buzz"
    MANUAL_REQ     = "User Manual Request"
    STOP_LOSS      = "Stop Loss Triggered"
