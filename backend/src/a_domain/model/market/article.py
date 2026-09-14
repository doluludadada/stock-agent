from datetime import datetime
from uuid import UUID, uuid4

from sqlmodel import Field, SQLModel

from a_domain.types.enums import ContentType, InformationSource


class Article(SQLModel):
    id: UUID = Field(default_factory=uuid4)  # Identity
    stock_id: str  # Stock
    source: InformationSource  # Source
    title: str  # Title
    content: str  # Content
    url: str | None = None  # Link
    author: str | None = None  # Author
    content_type: ContentType = Field(default=ContentType.DISCUSSION)  # Type
    published_at: datetime  # Published
    fetched_at: datetime = Field(default_factory=datetime.now)  # Fetched
    raw_metadata: dict | None = Field(default=None)  # Metadata
