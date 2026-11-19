from a_domain.model.analysis.sentiment import SocialSentiment


def row_of(sentiment: SocialSentiment) -> dict[str, int]:
    return {"posts": sentiment.posts, "bullish": sentiment.bullish}
