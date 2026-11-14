from typing import Self

from pydantic import model_validator
from sqlmodel import Field, SQLModel


class PriceRow(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    close: float = 0

    @model_validator(mode="after")
    def close_is_not_negative(self) -> Self:
        assert self.close >= 0, "close must be non-negative"
        return self

    def to_price(self) -> float:
        return self.close
