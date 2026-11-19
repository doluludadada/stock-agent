from collections.abc import Iterable
from typing import Annotated, Self

from pydantic import Field, NonNegativeInt, PositiveInt, model_validator
from pydantic.dataclasses import dataclass

from a_domain.model.market.article import Article
from a_domain.types.enums import SentimentConsensus, SentimentLabel
from a_domain.types.values import Fraction


@dataclass(frozen=True)
class SentimentConsensusRule:
    """
    Decides what a stock's opinions say together. Fewer than `min_opinions` opinions are UNCLEAR. Otherwise the stance
    whose share of the opinions reaches `consensus_share` is the consensus. Bullish and bearish are counted side by side
    and never netted, so an even bullish/bearish split is DISAGREEMENT, not NEUTRAL.
    """

    min_opinions: PositiveInt
    consensus_share: Annotated[float, Field(gt=0.5, le=1)]
    """Above one half, so only one stance can reach it."""

    def apply(self, bullish: int, bearish: int, neutral: int) -> SentimentConsensus:
        opinions = bullish + bearish + neutral

        if opinions < self.min_opinions:
            return SentimentConsensus.UNCLEAR

        stances = {SentimentConsensus.BULLISH: bullish, SentimentConsensus.BEARISH: bearish, SentimentConsensus.NEUTRAL: neutral}

        for consensus, count in stances.items():
            if count / opinions >= self.consensus_share:
                return consensus

        return SentimentConsensus.DISAGREEMENT


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


@dataclass(frozen=True)
class SocialSentimentRule:
    """
    Tallies a stock's classified posts. A post classified below `min_confidence` counts as UNCLEAR, and a post without a
    sentiment is not counted.
    """

    min_confidence: Fraction
    consensus_rule: SentimentConsensusRule

    def apply(self, classified: Iterable[Article], post_count: int) -> SocialSentiment:
        labels = [
            post.sentiment if post.sentiment_confidence >= self.min_confidence else SentimentLabel.UNCLEAR
            for post in classified
            if post.sentiment is not None and post.sentiment_confidence is not None
        ]
        bullish, bearish, neutral = (
            labels.count(label) for label in (SentimentLabel.BULLISH, SentimentLabel.BEARISH, SentimentLabel.NEUTRAL)
        )

        return SocialSentiment(
            posts=post_count,
            bullish=bullish,
            bearish=bearish,
            neutral=neutral,
            unclear=labels.count(SentimentLabel.UNCLEAR),
            consensus=self.consensus_rule.apply(bullish, bearish, neutral),
        )
