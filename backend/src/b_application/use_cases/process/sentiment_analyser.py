from a_domain.model.analysis.social_sentiment import SocialSentiment
from a_domain.model.market.stock import Stock
from a_domain.ports.ai.sentiment_classifier import ISentimentClassifier
from a_domain.ports.system.logging_provider import ILoggingProvider
from b_application.schemas.pipeline_status import PipelineStatus


class SentimentAnalyser:
    """
    Tallies the social sentiment of Buzz stocks for the Buzz report.

    It writes only status.sentiment_by_stock_id. Trading steps never read it.
    """

    def __init__(self, classifier: ISentimentClassifier, logger: ILoggingProvider) -> None:
        self._classifier = classifier
        self._logger = logger

    async def execute(self, stocks: list[Stock], status: PipelineStatus) -> None:
        self._logger.info(f"Classifying social sentiment for {len(stocks)} buzz stocks.")

        for stock in stocks:
            posts = [article for article in stock.articles if article.source.is_social]

            if not posts:
                continue

            try:
                classifications = await self._classifier.classify(stock.stock_id, posts)
                status.sentiment_by_stock_id[stock.stock_id] = SocialSentiment.tally(classifications, posts=len(posts))
            except Exception as error:
                message = f"Sentiment analysis failed for {stock.stock_id}: {error}"
                self._logger.error(message)
                status.stats.add_error(message)

        self._logger.info(f"Social sentiment completed: {len(status.sentiment_by_stock_id)}/{len(stocks)} stocks.")
