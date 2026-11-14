import json
from datetime import date
from typing import ClassVar

from sqlalchemy import Text
from sqlmodel import Field, SQLModel

from a_domain.ports.ai.system_writing_log import SystemWriting


class SystemWritingDTO(SQLModel, table=True):
    """One round of the site's own writing: the primary key keeps one per session. The stocks are saved as JSON."""

    __tablename__: ClassVar[str] = "system_writings"

    session_date: date = Field(primary_key=True)
    started_on: date
    stock_ids: str = Field(sa_type=Text)

    def to_domain(self) -> SystemWriting:
        return SystemWriting(session=self.session_date, started_on=self.started_on, stock_ids=json.loads(self.stock_ids))


class SystemTextDTO(SQLModel, table=True):
    """
    A brief or a card the site's own writing claimed, by the table that holds it, the stock and the day. Such a text
    takes none of the stocks viewers' requests may claim a day (stock_page.brief.daily_stocks, stock_page.card.daily_stocks).
    A shared table: no owner.
    """

    __tablename__: ClassVar[str] = "system_texts"

    text_table: str = Field(primary_key=True)
    stock_id: str = Field(primary_key=True)
    day: date = Field(primary_key=True)


class SystemAiCallDTO(SQLModel, table=True):
    """How many paid AI calls the site's own writing made on one Taiwan calendar day. A shared table: no owner."""

    __tablename__: ClassVar[str] = "system_ai_calls"

    day: date = Field(primary_key=True)
    calls: int = 0
