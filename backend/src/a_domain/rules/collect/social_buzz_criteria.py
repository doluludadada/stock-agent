

from dataclasses import dataclass


@dataclass(frozen=True)
class SocialBuzzCriteria:
    """
    Social Buzz Metrics Evaluation Rule.

    Evaluates quantitative interest levels across social platforms to classify
    whether a stock qualifies as "Trending".
    """


    min_mentions: int
    min_push_count: int
    """
    Implements a simple stateless criteria for trend classification.

    Attributes:
        min_mentions (int): The lower boundary of mentions needed within a time block.
        min_push_count (int): The combined push (upvote) score needed to confirm trend strength.
    """
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
