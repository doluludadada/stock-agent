from a_domain.model.analysis.sentiment import SocialSentiment


def sentiment_line(sentiment: SocialSentiment) -> str:
    return f"{sentiment.bullish} of {sentiment.posts} posts are bullish"
