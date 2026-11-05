from typing import Self

from pydantic import NonNegativeInt, model_validator
from pydantic.dataclasses import dataclass

from a_domain.types.enums import SentimentConsensus


@dataclass(frozen=True)
class SocialSentiment:
    """
    Stock-level sentiment of a Buzz stock's social posts, as SocialSentimentRule tallies it. Report only: it never
    feeds trading decisions. Ratios are shares of the opinions (bullish, bearish and neutral).
    """

    posts: NonNegativeInt
    bullish: NonNegativeInt
    bearish: NonNegativeInt
    neutral: NonNegativeInt
    unclear: NonNegativeInt
    consensus: SentimentConsensus

    @model_validator(mode="after")
    def classifies_at_most_the_posts(self) -> Self:
        if self.classified > self.posts:
            raise ValueError("cannot classify more posts than were given")

        return self

    @property
    def classified(self) -> int:
        return self.bullish + self.bearish + self.neutral + self.unclear

    @property
    def opinions(self) -> int:
        return self.bullish + self.bearish + self.neutral

    @property
    def bullish_ratio(self) -> float:
        return self.bullish / self.opinions if self.opinions else 0.0

    @property
    def bearish_ratio(self) -> float:
        return self.bearish / self.opinions if self.opinions else 0.0

    @property
    def neutral_ratio(self) -> float:
        return self.neutral / self.opinions if self.opinions else 0.0
