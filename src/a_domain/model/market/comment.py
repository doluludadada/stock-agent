# TODO: 未來功能 - 社群評論分析 (目前未使用)
from datetime import datetime
from uuid import UUID, uuid4

from sqlmodel import Field, SQLModel


class Comment(SQLModel):
    """
    Represents reactions to an Article.
    Critical for Sentiment Analysis (e.g., Identifying divergence between Post and Comments).
    """

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    article_id: UUID = Field(index=True)  # Foreign Key reference in Logic

    author: str | None = None
    content: str

    # E.g., "PUSH", "BOO", "ARROW" for PTT
    reaction_type: str | None = None

    published_at: datetime = Field(default_factory=datetime.now)
