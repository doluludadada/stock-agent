from datetime import datetime
from typing import ClassVar

from sqlmodel import Field, SQLModel

from c_infrastructure.database.utc_datetime import UtcDateTime


class RequestPaceDTO(SQLModel, table=True):
    """
    When the next request to one host may leave: the primary key keeps one row per host, which every process on this
    database reserves its requests in (SharedRequestPace). A shared table: no owner.
    """

    __tablename__: ClassVar[str] = "request_paces"

    host: str = Field(primary_key=True)
    next_at: datetime = Field(sa_type=UtcDateTime)
