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
