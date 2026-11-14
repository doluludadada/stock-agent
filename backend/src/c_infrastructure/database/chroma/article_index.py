import asyncio
from collections.abc import Sequence
from datetime import date
from hashlib import sha256
from typing import Any, override

import numpy
from chromadb.api import ClientAPI
from chromadb.api.types import Metadata

from a_domain.model.market.article import Article
from a_domain.ports.ai.article_index import IArticleIndex
from a_domain.ports.ai.text_embedder import ITextEmbedder
from a_domain.ports.system.market_clock import IMarketClock
from c_infrastructure.database.chroma.schema import ChromaMetadataKey, ChromaResultKey


class ChromaArticleIndex(IArticleIndex):
    """
    One Chroma collection of the article store's vectors, shared by every user and apart from the collections of chat
    and of decisions. An entry is a vector under `<stock id>|<article key>` with the stock, the day the article was
    published in the exchange's zone and the digest of the text the vector was computed from: no title, no text and no
    address. The vectors come from `embedder`, never from Chroma's own model, and compare by cosine distance. Every
    Chroma call runs off the event loop, and one sync runs at a time, so two requests never embed the same article.
    dependencies.py names the collection; `text_length` is how much of an article's kept text a vector reads.
    """

    def __init__(
        self, client: ClientAPI, collection_name: str, embedder: ITextEmbedder, market_clock: IMarketClock, text_length: int
    ) -> None:
        self._collection = client.get_or_create_collection(
            name=collection_name, embedding_function=None, configuration={"hnsw": {"space": "cosine"}}
        )
        self._embedder = embedder
        self._market_clock = market_clock
        self._text_length = text_length
        self._syncing = asyncio.Lock()

    @override
    async def sync(self, stock_id: str, articles: Sequence[Article]) -> int:
        texts = {f"{stock_id}|{article.key}": embedded_text(article, self._text_length) for article in articles}
        days = [self._market_clock.to_market_datetime(article.published_at).date() for article in articles]
        described: dict[str, Metadata] = {
            entry: {
                ChromaMetadataKey.STOCK_ID: stock_id,
                ChromaMetadataKey.PUBLISHED_DAY: day.toordinal(),
                ChromaMetadataKey.TEXT_DIGEST: sha256(text.encode()).hexdigest(),
            }
            for (entry, text), day in zip(texts.items(), days, strict=True)
        }

        async with self._syncing:
            held = await asyncio.to_thread(self._collection.get, where={ChromaMetadataKey.STOCK_ID: stock_id}, include=["metadatas"])
            current = dict(zip(held.get(ChromaResultKey.IDS) or [], held.get(ChromaResultKey.METADATAS) or [], strict=True))
            gone = [entry for entry in current if entry not in texts]
            missing = [entry for entry in texts if current.get(entry) != described[entry]]

            if gone:
                await asyncio.to_thread(self._collection.delete, ids=gone)

            if missing:
                vectors = numpy.asarray(await self._embedder.embed([texts[entry] for entry in missing]), dtype=numpy.float32)
                metadatas = [described[entry] for entry in missing]
                await asyncio.to_thread(self._collection.upsert, ids=missing, embeddings=vectors, metadatas=metadatas)

        return len(missing)

    @override
    async def search(self, stock_id: str, query: str, first: date | None, last: date | None, limit: int) -> list[str]:
        bounds: list[dict[str, Any]] = [{ChromaMetadataKey.STOCK_ID: stock_id}]

        if first is not None:
            bounds.append({ChromaMetadataKey.PUBLISHED_DAY: {"$gte": first.toordinal()}})

        if last is not None:
            bounds.append({ChromaMetadataKey.PUBLISHED_DAY: {"$lt": last.toordinal()}})

        where: Any = bounds[0] if len(bounds) == 1 else {"$and": bounds}
        vector = (await self._embedder.embed([query]))[0]
        found = await asyncio.to_thread(self._collection.query, query_embeddings=[vector], n_results=limit, where=where, include=[])

        return [entry.partition("|")[2] for entry in (found.get(ChromaResultKey.IDS) or [[]])[0]]


def embedded_text(article: Article, text_length: int) -> str:
    """What of an article its vector stands for: its title, then the text kept with it, cut to the length the index reads."""
    text = article.content[:text_length]
    return article.title if not text or text == article.title else f"{article.title}\n{text}"
