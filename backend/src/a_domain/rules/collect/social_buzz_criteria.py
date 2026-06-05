from dataclasses import dataclass

import icontract


@icontract.invariant(lambda self: self.min_mentions >= 0)
@icontract.invariant(lambda self: self.min_push_count >= 0)
@dataclass(frozen=True)
class SocialBuzzCriteria:
    """
    Social Buzz Metrics Evaluation Rule.

    Evaluates quantitative interest levels across social platforms to classify
    whether a stock qualifies as "Trending".
    """

    min_mentions: int
    min_push_count: int

    # TODO: Wire this up for future use
    def is_trending(self, mention_count: int, push_sum: int) -> bool:
        """
        Verifies if social metrics cross either threshold to qualify as buzz.

        Args:
            mention_count (int): Number of unique discussions detected.
            push_sum (int): Accumulated thread popularity score.

        Returns:
            bool: True if the buzz qualifies, False otherwise.
        """
        return mention_count >= self.min_mentions or push_sum >= self.min_push_count
