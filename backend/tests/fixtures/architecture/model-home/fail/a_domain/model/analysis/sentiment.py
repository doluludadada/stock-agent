from pydantic.dataclasses import dataclass


@dataclass(frozen=True)
class SocialSentiment:
    posts: int
    bullish: int

    @property
    def bullish_ratio(self) -> float:
        return self.bullish / self.posts if self.posts else 0.0
