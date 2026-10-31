from typing import override

from sqlmodel import col, select

from a_domain.model.analysis.sentiment_classification import SentimentClassification
from a_domain.ports.ai.sentiment_repository import ISentimentRepository
from a_domain.types.enums import SentimentLabel
from c_infrastructure.database.db_connector import DatabaseConnector
from c_infrastructure.database.models.article_sentiment_dto import ArticleSentimentDTO


class SentimentRepository(ISentimentRepository):
    def __init__(self, db: DatabaseConnector) -> None:
        self._db = db

    @override
    async def find_classifications(self, stock_id: str, urls: list[str]) -> dict[str, SentimentClassification]:
        if not urls:
            return {}

        async with self._db.get_session() as session:
            statement = select(ArticleSentimentDTO).where(
                ArticleSentimentDTO.stock_id == stock_id, col(ArticleSentimentDTO.article_url).in_(urls)
            )
            rows = (await session.execute(statement)).scalars().all()

        return {row.article_url: SentimentClassification(label=SentimentLabel(row.label), confidence=row.confidence) for row in rows}

    @override
    async def save_classifications(self, stock_id: str, classifications: dict[str, SentimentClassification]) -> None:
        if not classifications:
            return

        async with self._db.get_session() as session:
            for url, classification in classifications.items():
                row = ArticleSentimentDTO(
                    stock_id=stock_id, article_url=url, label=classification.label, confidence=classification.confidence
                )
                await session.merge(row)

            await session.commit()
