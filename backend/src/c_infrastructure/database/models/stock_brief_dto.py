from datetime import date, datetime
from typing import Any, ClassVar, Self

from pydantic import TypeAdapter
from sqlalchemy import Column, Text
from sqlmodel import Field, SQLModel

from a_domain.model.analysis.stock_brief import BriefSentence, BriefSource, StockBrief
from a_domain.types.enums import BriefLanguage, BriefStatus
from c_infrastructure.database.utc_datetime import UtcDateTime


class StockBriefDTO(SQLModel, table=True):
    """
    The AI's brief of one stock on one Taipei calendar day, shared by every user: the primary key keeps one per stock
    and day. `status`, `language` and `model` are saved as text, and the sentences with the sources they cite as JSON.
    """

    __tablename__: ClassVar[str] = "stock_briefs"

    stock_id: str = Field(primary_key=True)
    day: date = Field(primary_key=True)
    status: str
    language: str
    model: str
    claimed_at: datetime = Field(sa_type=UtcDateTime)
    written_at: datetime | None = Field(default=None, sa_type=UtcDateTime)
    window_first: date | None = None
    window_last: date | None = None
    price_change: float | None = None
    company: str = Field(sa_column=Column(Text, nullable=False))
    movement: str = Field(sa_column=Column(Text, nullable=False))
    sources: str = Field(sa_column=Column(Text, nullable=False))

    SENTENCES: ClassVar[TypeAdapter[list[BriefSentence]]] = TypeAdapter(list[BriefSentence])
    SOURCES: ClassVar[TypeAdapter[list[BriefSource]]] = TypeAdapter(list[BriefSource])

    @classmethod
    def values_of(cls, brief: StockBrief) -> dict[str, Any]:
        """The row's columns for `brief`."""
        return {
            "stock_id": brief.stock_id,
            "day": brief.day,
            "status": brief.status.value,
            "language": brief.language.value,
            "model": brief.model,
            "claimed_at": brief.claimed_at,
            "written_at": brief.written_at,
            "window_first": brief.window_first,
            "window_last": brief.window_last,
            "price_change": brief.price_change,
            "company": cls.SENTENCES.dump_json(brief.company).decode(),
            "movement": cls.SENTENCES.dump_json(brief.movement).decode(),
            "sources": cls.SOURCES.dump_json(brief.sources).decode(),
        }

    @classmethod
    def from_domain(cls, brief: StockBrief) -> Self:
        return cls(**cls.values_of(brief))

    def to_domain(self) -> StockBrief:
        return StockBrief(
            stock_id=self.stock_id,
            day=self.day,
            status=BriefStatus(self.status),
            language=BriefLanguage(self.language),
            model=self.model,
            claimed_at=self.claimed_at,
            written_at=self.written_at,
            window_first=self.window_first,
            window_last=self.window_last,
            price_change=self.price_change,
            company=self.SENTENCES.validate_json(self.company),
            movement=self.SENTENCES.validate_json(self.movement),
            sources=self.SOURCES.validate_json(self.sources),
        )
