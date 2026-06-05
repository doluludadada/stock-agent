# backend/src/c_infrastructure/database/models/article_dto.py
from typing import ClassVar
from uuid import UUID

from sqlalchemy import JSON, Column, String
from sqlmodel import Field

from a_domain.model.market.article import Article
from a_domain.types.enums import ContentType, InformationSource


class ArticleDTO(Article, table=True):
    """
    Infrastructure Database Model for Article.
    Inherits all business fields from the Domain Model, but adds SQLAlchemy Table instructions.
    """

    __tablename__: ClassVar[str] = "articles"  # pyright: ignore[reportIncompatibleVariableOverride]

    id: UUID = Field(default=None, primary_key=True)
    source: InformationSource = Field(sa_column=Column("source", String))

    content_type: ContentType = Field(default=ContentType.DISCUSSION, sa_column=Column("content_type", String))
    raw_metadata: dict | None = Field(default=None, sa_column=Column(JSON))
