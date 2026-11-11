from datetime import datetime
from typing import Any, ClassVar, Self
from uuid import UUID

from pydantic import TypeAdapter
from sqlalchemy import JSON, Column, Index
from sqlmodel import Field, SQLModel

from a_domain.model.trading.backtest import Backtest
from c_infrastructure.database.utc_datetime import UtcDateTime

STORED_BACKTEST = TypeAdapter(Backtest)


class BacktestDTO(SQLModel, table=True):
    """One owner's saved backtest. The model is the `backtest` column as pydantic writes it; the other columns find it."""

    __tablename__: ClassVar[str] = "backtests"
    __table_args__ = (Index("ix_backtests_owner_created", "owner_id", "created_at"),)

    backtest_id: UUID = Field(primary_key=True)
    owner_id: str
    created_at: datetime = Field(sa_type=UtcDateTime)
    backtest: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))

    @classmethod
    def from_domain(cls, backtest: Backtest, owner_id: str) -> Self:
        return cls(
            backtest_id=backtest.backtest_id,
            owner_id=owner_id,
            created_at=backtest.created_at,
            backtest=STORED_BACKTEST.dump_python(backtest, mode="json", exclude_computed_fields=True),
        )

    def to_domain(self) -> Backtest:
        return STORED_BACKTEST.validate_python(self.backtest)
