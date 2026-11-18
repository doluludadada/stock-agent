from datetime import date, datetime
from typing import ClassVar, Self

from pgvector.sqlalchemy import VECTOR
from sqlalchemy import DDL, Column, Text, event
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


ARTICLE_VECTOR_LENGTH = 512
"""
How many numbers each vector of article_vectors holds: the width of the last layer of the shipped embedding model
(stock_page.article_store.embedding, Xenova/bge-small-zh-v1.5), as its ONNX file declares it. A model of another width
needs an upgrade step that changes the column.
"""


class ArticleVectorDTO(SQLModel, table=True):
    """
    The article index's vector of one kept article (IArticleIndex), shared by every user, under the stock and key the
    article store keeps the article by: no title, no text and no address. `published_day` is the day the article was
    published in the exchange's zone, which a search bounds. `text_digest` is the SHA-256 of the text the vector was
    computed from, and `embedding_model` the identity of the model that computed it (EmbeddingConfig.identity), so a
    vector of other text or of another model is computed again rather than compared. Each vector stays in its row
    (STORAGE PLAIN): at 2 KB it is past the size PostgreSQL moves into its TOAST table, where a search, which compares
    every vector of the stock, would fetch each one on its own and take more than twice as long for a stock of 5,000.
    """

    __tablename__: ClassVar[str] = "article_vectors"

    stock_id: str = Field(primary_key=True)
    key: str = Field(primary_key=True)
    published_day: date
    text_digest: str
    embedding_model: str
    vector: list[float] = Field(sa_column=Column(VECTOR(ARTICLE_VECTOR_LENGTH), nullable=False))


event.listen(
    SQLModel.metadata.tables[ArticleVectorDTO.__tablename__],
    "after_create",
    DDL("ALTER TABLE article_vectors ALTER COLUMN vector SET STORAGE PLAIN"),
)

# Every create_all creates pgvector's extension before any table, as a new database's article_vectors needs its type.
# Where the database has it, the statement does nothing, whatever the role.
event.listen(SQLModel.metadata, "before_create", DDL("CREATE EXTENSION IF NOT EXISTS vector"))
