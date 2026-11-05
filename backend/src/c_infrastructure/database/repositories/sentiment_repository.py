import asyncio
from dataclasses import replace
from typing import override

from sqlmodel import col, select

from a_domain.model.market.article import Article
from a_domain.ports.ai.sentiment_repository import ISentimentRepository
from a_domain.types.enums import SentimentLabel
from c_infrastructure.database.db_connector import DatabaseConnector
from c_infrastructure.database.models.article_sentiment_dto import ArticleSentimentDTO


class SentimentRepository(ISentimentRepository):
    """
    The classified posts every user's Buzz scans share. One save at a time per process, every runtime's, under the
    lock CachedPriceProvider writes its bars with: two runs merging the same post at once would both insert it, and
    the second would fail on the key.
    """

    def __init__(self, db: DatabaseConnector, write_lock: asyncio.Lock) -> None:
        self._db = db
        self._write_lock = write_lock

    @override
    async def find_classified(self, stock_id: str, posts: list[Article]) -> list[Article]:
        urls = [post.url for post in posts if post.url]

        if not urls:
            return []

        async with self._db.get_session() as session:
            statement = select(ArticleSentimentDTO).where(
                ArticleSentimentDTO.stock_id == stock_id, col(ArticleSentimentDTO.article_url).in_(urls)
            )
            rows = {row.article_url: row for row in (await session.execute(statement)).scalars().all()}

        return [
            replace(post, sentiment=SentimentLabel(rows[post.url].label), sentiment_confidence=rows[post.url].confidence)
            for post in posts
            if post.url in rows
        ]

    @override
    async def save_classified(self, stock_id: str, posts: list[Article]) -> None:
        rows = {
            post.url: ArticleSentimentDTO(
                stock_id=stock_id, article_url=post.url, label=post.sentiment, confidence=post.sentiment_confidence
            )
            for post in posts
            if post.url and post.sentiment is not None and post.sentiment_confidence is not None
        }

        if not rows:
            return

        async with self._write_lock, self._db.get_session() as session:
            for row in rows.values():
                await session.merge(row)

            await session.commit()
