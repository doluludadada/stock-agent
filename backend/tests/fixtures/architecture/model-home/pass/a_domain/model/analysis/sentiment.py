from pydantic.dataclasses import dataclass


@dataclass(frozen=True)
class SocialSentiment:
    posts: int
    bullish: int
