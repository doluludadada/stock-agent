from collections.abc import Iterable
from typing import Annotated

from pydantic import Field, PositiveInt
from pydantic.dataclasses import dataclass

from a_domain.model.analysis.social_sentiment import SocialSentiment
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
