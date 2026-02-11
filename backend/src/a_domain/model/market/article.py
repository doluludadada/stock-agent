from datetime import datetime
from uuid import UUID, uuid4

from backend.src.a_domain.types.enums import ContentType, InformationSource
from sqlmodel import Field, SQLModel


class Article(SQLModel):
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    stock_id: str = Field(index=True)
    source: InformationSource
    title: str
    content: str
    url: str | None = None
    author: str | None = None
    content_type: ContentType = Field(default=ContentType.DISCUSSION)
    published_at: datetime
    fetched_at: datetime = Field(default_factory=datetime.now)
    raw_metadata: dict | None = Field(default=None)
