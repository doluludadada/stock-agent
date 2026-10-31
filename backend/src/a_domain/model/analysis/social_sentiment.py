from collections.abc import Iterable
from dataclasses import dataclass
from typing import ClassVar, Self

from icontract import invariant

from a_domain.model.analysis.sentiment_classification import SentimentClassification
from a_domain.types.enums import SentimentConsensus, SentimentLabel


@invariant(lambda self: min(self.bullish, self.bearish, self.neutral, self.unclear) >= 0)
@invariant(lambda self: self.classified <= self.posts, "cannot classify more posts than were given")
@dataclass(frozen=True)
class SocialSentiment:
    """
    Stock-level sentiment of a Buzz stock's social posts. Report only: it never feeds trading decisions.

    A classification below MIN_CONFIDENCE counts as UNCLEAR. Ratios are shares of the opinions
    (bullish, bearish and neutral). Bullish and bearish are counted side by side and never netted,
    so an even bullish/bearish split is DISAGREEMENT, not NEUTRAL.
    """

    MIN_CONFIDENCE: ClassVar[float] = 0.5
    MIN_OPINIONS: ClassVar[int] = 2
    CONSENSUS_SHARE: ClassVar[float] = 0.6

    posts: int
    bullish: int
    bearish: int
    neutral: int
    unclear: int

    @classmethod
    def tally(cls, classifications: Iterable[SentimentClassification], posts: int) -> Self:
        labels = [
            classification.label if classification.confidence >= cls.MIN_CONFIDENCE else SentimentLabel.UNCLEAR
            for classification in classifications
        ]

        return cls(
            posts=posts,
            bullish=labels.count(SentimentLabel.BULLISH),
            bearish=labels.count(SentimentLabel.BEARISH),
            neutral=labels.count(SentimentLabel.NEUTRAL),
            unclear=labels.count(SentimentLabel.UNCLEAR),
        )

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

    @property
    def consensus(self) -> SentimentConsensus:
        if self.opinions < self.MIN_OPINIONS:
            return SentimentConsensus.UNCLEAR

        shares = {
            SentimentConsensus.BULLISH: self.bullish_ratio,
            SentimentConsensus.BEARISH: self.bearish_ratio,
            SentimentConsensus.NEUTRAL: self.neutral_ratio,
        }

        # CONSENSUS_SHARE is above one half, so at most one label can reach it.
        for consensus, share in shares.items():
            if share >= self.CONSENSUS_SHARE:
                return consensus

        return SentimentConsensus.DISAGREEMENT
