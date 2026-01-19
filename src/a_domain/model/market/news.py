from datetime import datetime
from sqlmodel import SQLModel, Field


class News(SQLModel):
    """
    Represents a news article or forum post.
    """

    symbol: str = Field(index=True)
    title: str
    url: str
    source: str  # e.g., "Anue", "Yahoo", "PTT"
    content: str
    published_at: datetime
    fetched_at: datetime = Field(default_factory=datetime.now)
