from datetime import datetime
from typing import Self
from uuid import UUID, uuid4

from pydantic import ConfigDict, Field, model_validator
from pydantic.dataclasses import dataclass

from a_domain.types.enums import ContentType, InformationSource, SentimentLabel
from a_domain.types.values import Fraction


@dataclass(config=ConfigDict(validate_assignment=True), kw_only=True)
class Article:
    """A news article or social post about one stock. The two sentiment fields change together, through `dataclasses.replace`."""

    id: UUID = Field(default_factory=uuid4)
    stock_id: str
    source: InformationSource
    title: str
    content: str
    url: str | None = None
    author: str | None = None
    content_type: ContentType = ContentType.DISCUSSION
    published_at: datetime
    fetched_at: datetime
    engagement: int = Field(default=0, ge=0)
    """Reactions and replies counted by the source platform."""

    raw_metadata: dict | None = None

    sentiment: SentimentLabel | None = None
    """The stance the sentiment classifier read in the post. None until it is classified."""

    sentiment_confidence: Fraction | None = None
    """How confident the sentiment classifier is of that stance. None until it is classified."""

    @model_validator(mode="after")
    def classified_with_a_confidence(self) -> Self:
        if (self.sentiment is None) != (self.sentiment_confidence is None):
            raise ValueError("a post's sentiment and its confidence are set together")

        return self
