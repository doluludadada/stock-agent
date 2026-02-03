from datetime import datetime
from uuid import UUID, uuid4

from sqlmodel import Field, SQLModel

from backend.src.a_domain.types.enums import ContentType, InformationSource


class Article(SQLModel):
    """
    Represents the main body of text.
    It could be a PTT post, a News article, or a Financial Report summary.
    """

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    stock_id: str = Field(index=True)

    source: InformationSource
    title: str
    content: str
    url: str | None = None
    author: str | None = None

    # This is determined by Rules or AI, not the raw crawler.
    content_type: ContentType = Field(default=ContentType.DISCUSSION)

    published_at: datetime
    fetched_at: datetime = Field(default_factory=datetime.now)

    # Stores source-specific metrics (e.g., PTT push/boo counts, News view count)
    # Kept generic to keep the Domain clean.
    raw_metadata: dict | None = Field(default=None)


