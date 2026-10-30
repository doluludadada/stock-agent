from dataclasses import dataclass
from enum import StrEnum

from pydantic import BaseModel, field_validator


class PriceColumn(StrEnum):
    CLOSE = "close"

    def label(self) -> str:
        return self.value.title()


class FeedFailure(RuntimeError):
    def __str__(self) -> str:
        return "feed failed"


class FeedTimeout(FeedFailure):
    def describe(self) -> str:
        return "feed timed out"


class Quote(BaseModel):
    price: float

    @field_validator("price")
    @classmethod
    def _positive(cls, value: float) -> float:
        return abs(value)


class DailyQuote(Quote):
    def describe(self) -> str:
        return str(self.price)


@dataclass(frozen=True)
class Window:
    days: int

    def _half(self) -> int:
        return self.days // 2
