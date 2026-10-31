from collections.abc import Iterable
from dataclasses import dataclass

from icontract import invariant

from a_domain.model.analysis.sentiment_classification import SentimentClassification
from a_domain.model.analysis.social_sentiment import SocialSentiment
from a_domain.types.enums import SentimentConsensus, SentimentLabel


@invariant(lambda self: self.min_opinions >= 1)
@invariant(lambda self: 0.5 < self.consensus_share <= 1, "consensus_share must be above one half, so only one stance can reach it")
@dataclass(frozen=True)
class SentimentConsensusRule:
    """
    Decides what a stock's opinions say together. Fewer than `min_opinions` opinions are UNCLEAR. Otherwise the stance
    whose share of the opinions reaches `consensus_share` is the consensus. Bullish and bearish are counted side by side
    and never netted, so an even bullish/bearish split is DISAGREEMENT, not NEUTRAL.
    """

    min_opinions: int
    consensus_share: float

    def apply(self, bullish: int, bearish: int, neutral: int) -> SentimentConsensus:
        opinions = bullish + bearish + neutral

        if opinions < self.min_opinions:
            return SentimentConsensus.UNCLEAR

        stances = {SentimentConsensus.BULLISH: bullish, SentimentConsensus.BEARISH: bearish, SentimentConsensus.NEUTRAL: neutral}

        for consensus, count in stances.items():
            if count / opinions >= self.consensus_share:
                return consensus

        return SentimentConsensus.DISAGREEMENT


@invariant(lambda self: 0 <= self.min_confidence <= 1)
@dataclass(frozen=True)
class SocialSentimentRule:
    """Tallies a stock's classified posts. A classification below `min_confidence` counts as UNCLEAR."""

    min_confidence: float
    consensus_rule: SentimentConsensusRule

    def apply(self, classifications: Iterable[SentimentClassification], posts: int) -> SocialSentiment:
        labels = [
            classification.label if classification.confidence >= self.min_confidence else SentimentLabel.UNCLEAR
            for classification in classifications
        ]
        bullish, bearish, neutral = (
            labels.count(label) for label in (SentimentLabel.BULLISH, SentimentLabel.BEARISH, SentimentLabel.NEUTRAL)
        )

        return SocialSentiment(
            posts=posts,
            bullish=bullish,
            bearish=bearish,
            neutral=neutral,
            unclear=labels.count(SentimentLabel.UNCLEAR),
            consensus=self.consensus_rule.apply(bullish, bearish, neutral),
        )
