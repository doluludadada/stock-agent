from a_domain.model.analysis.ai_report import AiReport
from a_domain.model.analysis.sentiment import SocialSentiment


class SentimentShare:
    async def execute(self, sentiment: SocialSentiment, report: AiReport) -> float:
        return sentiment.bullish / sentiment.posts if report.score else 0.0
