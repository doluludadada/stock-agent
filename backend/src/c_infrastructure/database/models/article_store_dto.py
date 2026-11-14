from datetime import date, datetime
from typing import ClassVar, Self

from sqlalchemy import Column, Text
from sqlmodel import Field, SQLModel

from a_domain.model.market.article import Article
from a_domain.types.enums import ContentType, InformationSource
from c_infrastructure.database.utc_datetime import UtcDateTime


class StoredArticleDTO(SQLModel, table=True):
    """
    One article the site read about one stock, shared by every user: the primary key keeps it once per stock under its
    key (Article.key). `source` and `content_type` are saved as text. `content` is the text the site may hold of it,
    empty for an article kept by its title and address. `stored_at` is when it was first kept or last replaced.
    """

    __tablename__: ClassVar[str] = "stored_articles"

    stock_id: str = Field(primary_key=True)
    key: str = Field(primary_key=True)
    source: str
    content_type: str
    title: str = Field(sa_column=Column(Text, nullable=False))
    content: str = Field(sa_column=Column(Text, nullable=False))
    url: str | None = None
    published_at: datetime = Field(sa_type=UtcDateTime, index=True)
    """Indexed on its own: retention drops by age across every stock."""

    stored_at: datetime = Field(sa_type=UtcDateTime)
    clause: str | None = None
    fact_date: date | None = None

    @classmethod
    def from_domain(cls, article: Article, stored_at: datetime) -> Self:
        return cls(
            stock_id=article.stock_id,
            key=article.key,
            source=article.source.value,
            content_type=article.content_type.value,
            title=article.title,
            content=article.content,
            url=article.url,
            published_at=article.published_at,
            stored_at=stored_at,
            clause=article.clause,
            fact_date=article.fact_date,
        )

    def to_domain(self, published_at: datetime) -> Article:
        """The article as read when it was kept, published at `published_at`, the row's instant in the zone the caller shows."""
        return Article(
            stock_id=self.stock_id,
            source=InformationSource(self.source),
            content_type=ContentType(self.content_type),
            title=self.title,
            content=self.content,
            url=self.url,
            published_at=published_at,
            fetched_at=self.stored_at,
            clause=self.clause,
            fact_date=self.fact_date,
        )
