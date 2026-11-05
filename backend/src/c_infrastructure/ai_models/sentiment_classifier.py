from datetime import UTC, datetime
from typing import override

from a_domain.model.chat.message import Message
from a_domain.model.market.article import Article
from a_domain.ports.ai.ai_provider import IAiProvider
from a_domain.ports.ai.sentiment_classifier import ISentimentClassifier
from a_domain.ports.ai.sentiment_repository import ISentimentRepository
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.rules.ai.parser import parse_sentiment_reply
from a_domain.rules.ai.prompt import SentimentPromptBuilder
from a_domain.types.enums import MessageRole
from b_application.config.app_config import AppConfig


class AiSentimentClassifier(ISentimentClassifier):
    """
    Classifies social posts with the configured AI provider, one call per stock for its posts not classified before.

    Classifications are kept by (stock_id, post URL). The URL, not the content, identifies a post,
    because PTT content starts with a reaction count that grows over time.
    """

    def __init__(
        self, ai_provider: IAiProvider, sentiment_repository: ISentimentRepository, config: AppConfig, logger: ILoggingProvider
    ) -> None:
        if not config.prompts.social_sentiment:
            raise ValueError("prompts.social_sentiment is empty. Add social_sentiment_prompt to config/instructions.yaml.")

        self._ai_provider = ai_provider
        self._sentiment_repository = sentiment_repository
        self._prompt_builder = SentimentPromptBuilder(
            template=config.prompts.social_sentiment, max_content_length=config.ai.article_content_length
        )
        self._logger = logger

    @override
    async def classify(self, stock_id: str, posts: list[Article]) -> list[Article]:
        cached = await self._sentiment_repository.find_classified(stock_id, posts)
        cached_urls = {post.url for post in cached}
        uncached = [post for post in posts if post.url not in cached_urls]

        self._logger.info(f"Sentiment cache for {stock_id}: {len(posts) - len(uncached)}/{len(posts)} posts cached.")

        if not uncached:
            return cached

        prompt = Message(role=MessageRole.USER, content=self._prompt_builder.apply(stock_id, uncached), timestamp=datetime.now(UTC))
        reply = await self._ai_provider.generate_reply(messages=(prompt,))
        fresh = parse_sentiment_reply(reply.content, uncached)

        await self._sentiment_repository.save_classified(stock_id, fresh)

        return [*cached, *fresh]
