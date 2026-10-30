import enum
from enum import StrEnum


class Side(StrEnum):
    BUY = "buy"


class OrderStatus(enum.StrEnum):
    OPEN = "open"
