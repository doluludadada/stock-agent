import json

from sqlmodel import col, select

from a_domain.model.analysis.social_sentiment import SentimentClassification
from a_domain.model.chat.message import Message
from a_domain.model.market.article import Article
from a_domain.ports.ai.ai_provider import IAiProvider
from a_domain.ports.ai.sentiment_classifier import ISentimentClassifier
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.types.enums import MessageRole, SentimentLabel
from b_application.schemas.config import AppConfig
from c_infrastructure.database.db_connector import DatabaseConnector
from c_infrastructure.database.models.article_sentiment_dto import ArticleSentimentDTO


class AiSentimentClassifier(ISentimentClassifier):
    """
    Classifies social posts with the configured AI provider, one call per stock for its uncached posts.

    Classifications are cached by (stock_id, post URL). The URL, not the content, identifies a post,
    because PTT content starts with a reaction count that grows over time.
    """

    def __init__(self, ai_provider: IAiProvider, db: DatabaseConnector, config: AppConfig, logger: ILoggingProvider) -> None:
        if not config.prompts.social_sentiment:
            raise ValueError("prompts.social_sentiment is empty. Add social_sentiment_prompt to config/instructions.yaml.")

        self._ai_provider = ai_provider
        self._db = db
        self._template = config.prompts.social_sentiment
        self._max_content_length = config.ai.article_content_length
        self._logger = logger

    async def classify(self, stock_id: str, articles: list[Article]) -> list[SentimentClassification]:
        cached = await self._load_cached(stock_id, [article.url for article in articles if article.url])
        uncached = [article for article in articles if article.url not in cached]

        self._logger.info(f"Sentiment cache for {stock_id}: {len(articles) - len(uncached)}/{len(articles)} posts cached.")

        if not uncached:
            return list(cached.values())

        reply = await self._ai_provider.generate_reply(
            messages=(Message(role=MessageRole.USER, content=self._build_prompt(stock_id, uncached)),)
        )
        fresh = self._parse_reply(reply.content, uncached)

        await self._save(stock_id, fresh)

        return [*cached.values(), *(classification for _, classification in fresh)]

    def _build_prompt(self, stock_id: str, articles: list[Article]) -> str:
        posts_text = "\n\n".join(
            f"[{index}] Title: {article.title}\nContent: {article.content[: self._max_content_length]}"
            for index, article in enumerate(articles, 1)
        )
        return self._template.format(stock_id=stock_id, posts_text=posts_text)

    def _parse_reply(self, content: str, articles: list[Article]) -> list[tuple[Article, SentimentClassification]]:
        json_start = content.find("{")
        json_end = content.rfind("}") + 1

        try:
            items = json.loads(content[json_start:json_end]).get("posts") if json_start != -1 else None
        except json.JSONDecodeError as error:
            raise ValueError(f"Sentiment reply JSON is malformed: {error}") from error

        if not isinstance(items, list):
            raise ValueError("Sentiment reply has no posts list.")

        classified: dict[int, tuple[Article, SentimentClassification]] = {}

        for item in items:
            parsed = self._parse_item(item, len(articles))

            if parsed is not None and parsed[0] not in classified:
                index, classification = parsed
                classified[index] = (articles[index - 1], classification)

        if not classified:
            raise ValueError("Sentiment reply has no usable post classification.")

        return list(classified.values())

    def _parse_item(self, item: object, post_count: int) -> tuple[int, SentimentClassification] | None:
        if not isinstance(item, dict):
            return None

        index, label, confidence = item.get("index"), item.get("label"), item.get("confidence")

        if isinstance(index, bool) or not isinstance(index, int) or not 1 <= index <= post_count:
            return None

        if not isinstance(label, str) or label.strip().lower() not in SentimentLabel:
            return None

        if isinstance(confidence, bool) or not isinstance(confidence, int | float) or not 0 <= confidence <= 1:
            return None

        return index, SentimentClassification(label=SentimentLabel(label.strip().lower()), confidence=float(confidence))

    async def _load_cached(self, stock_id: str, urls: list[str]) -> dict[str, SentimentClassification]:
        if not urls:
            return {}

        async with self._db.get_session() as session:
            statement = select(ArticleSentimentDTO).where(
                ArticleSentimentDTO.stock_id == stock_id, col(ArticleSentimentDTO.article_url).in_(urls)
            )
            rows = (await session.execute(statement)).scalars().all()

        return {row.article_url: SentimentClassification(label=SentimentLabel(row.label), confidence=row.confidence) for row in rows}

    async def _save(self, stock_id: str, classified: list[tuple[Article, SentimentClassification]]) -> None:
        rows = [
            ArticleSentimentDTO(
                stock_id=stock_id, article_url=article.url, label=classification.label, confidence=classification.confidence
            )
            for article, classification in classified
            if article.url
        ]

        if not rows:
            return

        async with self._db.get_session() as session:
            for row in rows:
                await session.merge(row)

            await session.commit()
