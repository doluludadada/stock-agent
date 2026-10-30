from datetime import UTC, datetime
from typing import ClassVar

from sqlalchemy import Column, String
from sqlmodel import Field, SQLModel

from a_domain.types.enums import SentimentLabel


class ArticleSentimentDTO(SQLModel, table=True):
    """Cached classification of one social post, so the same public post is never classified twice."""

    __tablename__: ClassVar[str] = "article_sentiments"

    stock_id: str = Field(primary_key=True)
    article_url: str = Field(primary_key=True)
    label: SentimentLabel = Field(sa_column=Column(String, nullable=False))
    confidence: float
    classified_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
