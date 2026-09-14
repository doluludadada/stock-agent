# backend/src/a_domain/rules/collect/social_buzz_criteria.py

from dataclasses import dataclass

import icontract


@icontract.invariant(lambda self: self.min_mentions >= 0)
@icontract.invariant(lambda self: self.min_engagement >= 0)
@dataclass(frozen=True)
class SocialBuzzCriteria:
    """
    Social Buzz Metrics Evaluation Rule.

    Evaluates quantitative interest levels across social platforms to classify
    whether a stock qualifies as "Trending".
    """

    min_mentions: int
    min_engagement: int

    def is_trending(self, mention_count: int, engagement: int) -> bool:
        return mention_count >= self.min_mentions or engagement >= self.min_engagement
