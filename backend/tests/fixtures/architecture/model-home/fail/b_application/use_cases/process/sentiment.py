from a_domain.model.analysis.sentiment import SocialSentiment


class SentimentShare:
    async def execute(self, sentiment: SocialSentiment) -> float:
        return sentiment.bullish_ratio
