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
    TWSE = "TWSE"  # Taiwan Stock Exchange
    TPEX = "TPEX"  # Taipei Exchange (OTC)
    NASDAQ = "NASDAQ"
    NYSE = "NYSE"


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
    PENDING = "PENDING"  # Created in system, not sent to broker
    SUBMITTED = "SUBMITTED"  # Sent to broker
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"


class TimeInForce(StrEnum):
    ROD = "ROD"  # Rest of Day
    IOC = "IOC"  # Immediate or Cancel
    FOK = "FOK"  # Fill or Kill


class InformationSource(StrEnum):
    """Where the data comes from."""

    TWSE_MOPS = "TWSE_MOPS"  # Official Filings
    NEWS_MEDIA = "NEWS_MEDIA"  # Yahoo, Anue, etc.
    PTT_STOCK = "PTT_STOCK"  # Social: Professional Board
    PTT_GOSSIPING = "PTT_GOSSIPING"  # Social: General Board
    REUNION = "REUNION"  # CMoney / Stock Dog


class ContentType(StrEnum):
    """The nature of the content for AI weighting."""

    FACT = "FACT"  # High weight: Official data
    REPORT = "REPORT"  # Medium weight: News reporting
    ANALYSIS = "ANALYSIS"  # High/Med weight: Deep user analysis (Long form)
    DISCUSSION = "DISCUSSION"  # Low weight: Short comments
    NOISE = "NOISE"  # Ignore


class SentimentType(StrEnum):
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    NEUTRAL = "NEUTRAL"


class CandidateSource(StrEnum):
    """
    Identifies how a stock entered the analysis pipeline.
    """

    TECHNICAL_WATCHLIST = "TECHNICAL_WATCHLIST"  # From nightly technical screening (Cold)
    SOCIAL_BUZZ = "SOCIAL_BUZZ"  # From real-time social listening (Hot)
    MANUAL_INPUT = "MANUAL_INPUT"  # Manually specified by user


class AnalysisStage(StrEnum):
    """Tracks the lifecycle of an analysis context in the pipeline."""

    PENDING = "PENDING"
    DATA_COLLECTED = "DATA_COLLECTED"
    FILTERED_PASS = "FILTERED_PASS"  # Survived Technical Filter
    FILTERED_FAIL = "FILTERED_FAIL"  # Dropped
    ENRICHED = "ENRICHED"  # Articles collected
    ANALYZED = "ANALYZED"  # AI Scored
    DECIDED = "DECIDED"  # Signal Generated



