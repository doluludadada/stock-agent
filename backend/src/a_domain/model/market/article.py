from datetime import datetime
from uuid import UUID, uuid4

from sqlmodel import Field, SQLModel

from a_domain.types.enums import ContentType, InformationSource


class Article(SQLModel):
    """A news article or social post about one stock."""

    id: UUID = Field(default_factory=uuid4)
    stock_id: str
    source: InformationSource
    title: str
    content: str
    url: str | None = None
    author: str | None = None
    content_type: ContentType = Field(default=ContentType.DISCUSSION)
    published_at: datetime
    fetched_at: datetime
    engagement: int = Field(default=0, ge=0)
    """Reactions and replies counted by the source platform."""

    raw_metadata: dict | None = Field(default=None)
