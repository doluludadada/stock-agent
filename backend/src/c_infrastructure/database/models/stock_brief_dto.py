from datetime import date, datetime
from typing import Any, ClassVar, Self

from pydantic import TypeAdapter
from sqlalchemy import Text
from sqlmodel import Field, SQLModel

from a_domain.model.analysis.stock_brief import BriefSentence, BriefSource, StockBrief
from a_domain.types.enums import BriefLanguage, BriefStatus
from c_infrastructure.database.utc_datetime import UtcDateTime


class BriefColumns(SQLModel):
    """
    The columns of an AI text about one stock, shared by every user: the primary key keeps one per stock and Taipei
    calendar day. `status`, `language` and `model` are saved as text, and the sentences with the sources they cite as
    JSON. Each kind of text has a table of its own with these columns.
    """

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
    company: str = Field(sa_type=Text)
    movement: str = Field(sa_type=Text)
    sources: str = Field(sa_type=Text)

    SENTENCES: ClassVar[TypeAdapter[list[BriefSentence]]] = TypeAdapter(list[BriefSentence])
    SOURCES: ClassVar[TypeAdapter[list[BriefSource]]] = TypeAdapter(list[BriefSource])

    @classmethod
    def values_of(cls, brief: StockBrief) -> dict[str, Any]:
        """The row's columns for `brief`: those this table has."""
        values = {
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
            "fingerprint": brief.fingerprint,
        }
        return {name: value for name, value in values.items() if name in cls.model_fields}

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
            fingerprint=getattr(self, "fingerprint", None),
        )


class StockBriefDTO(BriefColumns, table=True):
    """The AI's brief of one stock on one Taipei calendar day."""

    __tablename__: ClassVar[str] = "stock_briefs"


class CompanyCardDTO(BriefColumns, table=True):
    """
    The AI's card of one company, under the Taipei calendar day it was claimed on: the newest written one is the
    company's card, and the earlier ones are kept. `fingerprint` is of the inputs it was written from.
    """

    __tablename__: ClassVar[str] = "company_cards"

    fingerprint: str | None = None


class WorldBriefDTO(BriefColumns, table=True):
    """The AI's world brief of one Taipei calendar day, under MarketScope.WORLD in `stock_id`. The past days' are kept."""

    __tablename__: ClassVar[str] = "world_briefs"
