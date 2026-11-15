from datetime import date
from typing import ClassVar

from sqlmodel import Field, SQLModel


class WorldIndicatorReadingDTO(SQLModel, table=True):
    """
    One world indicator's reading of one day, as its source served it, shared by every user: the primary key keeps one
    per indicator and day. `indicator` is saved as text.
    """

    __tablename__: ClassVar[str] = "world_indicator_readings"

    indicator: str = Field(primary_key=True)
    day: date = Field(primary_key=True)
    value: float
