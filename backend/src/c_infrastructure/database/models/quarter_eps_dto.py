from datetime import datetime
from typing import ClassVar, Self

from sqlalchemy import JSON, Column
from sqlmodel import Field, SQLModel

from a_domain.model.fundamentals.fiscal_quarter import FiscalQuarter
from a_domain.model.fundamentals.quarter_eps import QuarterEps
from a_domain.types.enums import MarketType
from c_infrastructure.database.utc_datetime import UtcDateTime


class QuarterEpsDTO(SQLModel, table=True):
    """One parsed MOPS t163sb04 page: cumulative basic EPS per company for one market and quarter."""

    __tablename__: ClassVar[str] = "mops_quarter_eps"

    market: str = Field(primary_key=True)
    year: int = Field(primary_key=True)
    quarter: int = Field(primary_key=True)
    fetched_at: datetime = Field(sa_type=UtcDateTime)
    cumulative_eps: dict[str, float] = Field(sa_column=Column(JSON, nullable=False))

    @classmethod
    def from_domain(cls, market: MarketType, page: QuarterEps) -> Self:
        return cls(
            market=market.value,
            year=page.quarter.year,
            quarter=page.quarter.quarter,
            fetched_at=page.fetched_at,
            cumulative_eps=dict(page.cumulative_eps),
        )

    def to_domain(self) -> QuarterEps:
        return QuarterEps(
            quarter=FiscalQuarter(self.year, self.quarter), cumulative_eps=self.cumulative_eps, fetched_at=self.fetched_at
        )
