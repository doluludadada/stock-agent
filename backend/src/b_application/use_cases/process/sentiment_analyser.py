from a_domain.model.analysis.social_sentiment import SocialSentiment
from a_domain.model.market.stock import Stock
from a_domain.model.system.stats import SystemStats
from a_domain.ports.ai.sentiment_classifier import ISentimentClassifier
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.rules.sentiment import SentimentConsensusRule, SocialSentimentRule
from b_application.config.app_config import AppConfig


class SentimentAnalyser:
    """
    Tallies the social sentiment of Buzz stocks for the Buzz report, by stock id. Trading steps never read it.
    """

    def __init__(self, classifier: ISentimentClassifier, config: AppConfig, logger: ILoggingProvider) -> None:
        self._classifier = classifier
        self._sentiment_rule = SocialSentimentRule(
            min_confidence=config.sentiment.min_confidence,
            consensus_rule=SentimentConsensusRule(
                min_opinions=config.sentiment.min_opinions, consensus_share=config.sentiment.consensus_share
            ),
        )
        self._logger = logger

    async def execute(self, stocks: list[Stock], stats: SystemStats) -> dict[str, SocialSentiment]:
        self._logger.info(f"Classifying social sentiment for {len(stocks)} buzz stocks.")
        sentiment_by_stock_id: dict[str, SocialSentiment] = {}

        for stock in stocks:
            posts = [article for article in stock.articles if article.source.is_social]

            if not posts:
                continue

            try:
                classified = await self._classifier.classify(stock.stock_id, posts)
                sentiment_by_stock_id[stock.stock_id] = self._sentiment_rule.apply(classified, post_count=len(posts))
                stats.sentiment_analysed += 1
            except Exception as error:
                message = f"Sentiment analysis failed for {stock.stock_id}: {error}"
                self._logger.error(message)
                stats.add_error(message)

        self._logger.info(f"Social sentiment completed: {len(sentiment_by_stock_id)}/{len(stocks)} stocks.")

        return sentiment_by_stock_id
