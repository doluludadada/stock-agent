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
    fetched_at: datetime  # Fetched
    engagement: int = Field(default=0, ge=0)  # Reactions and replies counted by the source platform
    raw_metadata: dict | None = Field(default=None)  # Metadata
