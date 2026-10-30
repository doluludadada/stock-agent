import enum
from enum import Enum, IntEnum, StrEnum


class Side(Enum):
    BUY = "buy"


class OrderKind(str, Enum):
    LIMIT = "limit"


class Priority(IntEnum):
    HIGH = 1


class Permission(enum.Flag):
    READ = 1


class OrderStatus(StrEnum):
    OPEN = "open"
