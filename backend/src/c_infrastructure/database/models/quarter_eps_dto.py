from datetime import datetime
from typing import ClassVar

from sqlalchemy import JSON, Column
from sqlmodel import Field, SQLModel


class QuarterEpsDTO(SQLModel, table=True):
    """One parsed MOPS t163sb04 page: cumulative basic EPS per company for one market and quarter."""

    __tablename__: ClassVar[str] = "mops_quarter_eps"

    market: str = Field(primary_key=True)
    year: int = Field(primary_key=True)
    quarter: int = Field(primary_key=True)
    fetched_at: datetime
    cumulative_eps: dict[str, float] = Field(sa_column=Column(JSON, nullable=False))
