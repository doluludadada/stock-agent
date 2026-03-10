from datetime import datetime
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from a_domain.types.enums import ContentType, InformationSource


class Article(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    stock_id: str
    source: InformationSource
    title: str
    content: str
    url: str | None = None
    author: str | None = None
    content_type: ContentType = Field(default=ContentType.DISCUSSION)
    published_at: datetime
    fetched_at: datetime = Field(default_factory=datetime.now)
    raw_metadata: dict | None = Field(default=None)
