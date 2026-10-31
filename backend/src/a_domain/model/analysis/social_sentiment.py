from dataclasses import dataclass

from icontract import invariant

from a_domain.types.enums import SentimentConsensus


@invariant(lambda self: min(self.bullish, self.bearish, self.neutral, self.unclear) >= 0)
@invariant(lambda self: self.classified <= self.posts, "cannot classify more posts than were given")
@dataclass(frozen=True)
class SocialSentiment:
    """
    Stock-level sentiment of a Buzz stock's social posts, as SocialSentimentRule tallies it. Report only: it never
    feeds trading decisions. Ratios are shares of the opinions (bullish, bearish and neutral).
    """

    posts: int
    bullish: int
    bearish: int
    neutral: int
    unclear: int
    consensus: SentimentConsensus

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
