from datetime import date
from typing import ClassVar

from sqlmodel import Field, SQLModel


class AiCallDTO(SQLModel, table=True):
    """How many paid AI calls one owner made on one Taiwan calendar day."""

    __tablename__: ClassVar[str] = "ai_calls"

    owner_id: str = Field(primary_key=True)
    day: date = Field(primary_key=True)
    calls: int = 0


class AiCallTotalDTO(SQLModel, table=True):
    """How many paid AI calls every owner together made on one Taiwan calendar day. A shared table: no owner."""

    __tablename__: ClassVar[str] = "ai_call_totals"

    day: date = Field(primary_key=True)
    calls: int = 0
