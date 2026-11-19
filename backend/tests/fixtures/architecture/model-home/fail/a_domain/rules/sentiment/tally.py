from pydantic.dataclasses import dataclass

from a_domain.model.analysis.sentiment import SocialSentiment


@dataclass(frozen=True)
class SentimentTallyRule:
    min_posts: int

    def apply(self, labels: list[str]) -> SocialSentiment:
        return SocialSentiment(posts=len(labels), bullish=labels.count("bullish"))
