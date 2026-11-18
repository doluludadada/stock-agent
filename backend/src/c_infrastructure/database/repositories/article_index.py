import asyncio
from collections.abc import Sequence
from datetime import date
from hashlib import sha256
from typing import Any, override

from sqlalchemy import Float, delete
from sqlmodel import col, select

from a_domain.model.market.article import Article
from a_domain.ports.ai.article_index import IArticleIndex
from a_domain.ports.ai.text_embedder import ITextEmbedder
from a_domain.ports.system.market_clock import IMarketClock
from c_infrastructure.database.db_connector import DatabaseConnector
from c_infrastructure.database.models.article_store_dto import ARTICLE_VECTOR_LENGTH, ArticleVectorDTO
from c_infrastructure.database.upsert import replacing

type VectorSource = tuple[date, str, str]
"""What a vector was computed from: its article's day in the exchange's zone, the digest of its text, and the model."""


class SqlArticleIndex(IArticleIndex):
    """
    The article_vectors table, shared by every user. The vectors come from `embedder`, whose identity the wiring names
    (`embedding_model`), and compare by cosine distance. A search reads the asked stock's vectors of this model through
    the primary key and compares every one of them, which is exact and fast for the articles one stock keeps
    (stock_page.article_store.max_per_stock, 5,000 at most), while an approximate index such as HNSW filters after its
    scan and can answer fewer keys than the stock holds. A sync embeds outside any transaction, and one sync runs at a
    time, so two requests never embed the same article. `text_length` is how much of an article's kept text a vector
    reads.
    """

    def __init__(
        self, db: DatabaseConnector, embedding_model: str, embedder: ITextEmbedder, market_clock: IMarketClock, text_length: int
    ) -> None:
        self._db = db
        self._embedding_model = embedding_model
        self._embedder = embedder
        self._market_clock = market_clock
        self._text_length = text_length
        self._syncing = asyncio.Lock()

    @override
    async def sync(self, stock_id: str, articles: Sequence[Article]) -> int:
        texts = {article.key: embedded_text(article, self._text_length) for article in articles}
        wanted: dict[str, VectorSource] = {
            article.key: (
                self._market_clock.to_market_datetime(article.published_at).date(),
                sha256(texts[article.key].encode()).hexdigest(),
                self._embedding_model,
            )
            for article in articles
        }

        async with self._syncing:
            held = await held_vectors(self._db, stock_id)
            missing = {key for key, source in wanted.items() if held.get(key) != source}
            gone = held.keys() - wanted.keys()

            if not missing and not gone:
                return 0

            if missing and (length := await self._embedder.vector_length()) != ARTICLE_VECTOR_LENGTH:
                raise ValueError(
                    f"The embedding model computes vectors of length {length}, not the {ARTICLE_VECTOR_LENGTH} of article_vectors"
                )

            keys = [key for key in wanted if key in missing]
            vectors = await self._embedder.embed([texts[key] for key in keys]) if keys else []
            rows = [vector_row(stock_id, key, wanted[key], vector) for key, vector in zip(keys, vectors, strict=True)]
            await replace_vectors(self._db, stock_id, gone, rows)

        return len(missing)

    @override
    async def search(self, stock_id: str, query: str, first: date | None, last: date | None, limit: int) -> list[str]:
        vector = (await self._embedder.embed([query]))[0]
        bounds = [col(ArticleVectorDTO.stock_id) == stock_id, col(ArticleVectorDTO.embedding_model) == self._embedding_model]

        if first is not None:
            bounds.append(col(ArticleVectorDTO.published_day) >= first)

        if last is not None:
            bounds.append(col(ArticleVectorDTO.published_day) < last)

        # pgvector's cosine_distance comparator is unknown to pyright on a SQLModel column, so its operator is named.
        distance = col(ArticleVectorDTO.vector).op("<=>", return_type=Float)(vector)
        closest = select(ArticleVectorDTO.key).where(*bounds).order_by(distance, col(ArticleVectorDTO.key)).limit(limit)

        async with self._db.get_session() as session:
            return list((await session.execute(closest)).scalars().all())


def embedded_text(article: Article, text_length: int) -> str:
    """What of an article its vector stands for: its title, then the text kept with it, cut to the length the index reads."""
    text = article.content[:text_length]
    return article.title if not text or text == article.title else f"{article.title}\n{text}"


async def held_vectors(db: DatabaseConnector, stock_id: str) -> dict[str, VectorSource]:
    """What each of the stock's vectors was computed from, by key."""
    held = select(
        col(ArticleVectorDTO.key),
        col(ArticleVectorDTO.published_day),
        col(ArticleVectorDTO.text_digest),
        col(ArticleVectorDTO.embedding_model),
    ).where(col(ArticleVectorDTO.stock_id) == stock_id)

    async with db.get_session() as session:
        return {key: (day, digest, model) for key, day, digest, model in (await session.execute(held)).all()}


def vector_row(stock_id: str, key: str, source: VectorSource, vector: list[float]) -> dict[str, Any]:
    """The row of article_vectors that holds the vector of the stock's article `key`, computed from `source`."""
    published_day, text_digest, embedding_model = source
    return {
        "stock_id": stock_id,
        "key": key,
        "published_day": published_day,
        "text_digest": text_digest,
        "embedding_model": embedding_model,
        "vector": vector,
    }


async def replace_vectors(db: DatabaseConnector, stock_id: str, gone: set[str], rows: list[dict[str, Any]]) -> None:
    """In one transaction: removes the stock's vectors of the `gone` articles, and writes `rows` over theirs."""
    async with db.get_session() as session:
        if gone:
            await session.execute(
                delete(ArticleVectorDTO).where(col(ArticleVectorDTO.stock_id) == stock_id, col(ArticleVectorDTO.key).in_(gone))
            )

        if rows:
            await session.execute(replacing(ArticleVectorDTO), rows)

        await session.commit()
