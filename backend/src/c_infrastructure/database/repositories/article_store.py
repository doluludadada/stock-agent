from collections.abc import Collection, Sequence
from datetime import timedelta
from typing import override

from sqlalchemy import delete
from sqlmodel import col, select

from a_domain.model.market.article import Article
from a_domain.ports.market.article_store import IArticleStore
from a_domain.ports.system.market_clock import IMarketClock
from c_infrastructure.database.db_connector import DatabaseConnector
from c_infrastructure.database.models.article_store_dto import StoredArticleDTO
from c_infrastructure.database.models.daily_close_archive_dto import replacing


class SqlArticleStore(IArticleStore):
    """
    The stored_articles table, shared by every user. A save reads what the table holds of the stocks named and writes
    only the articles that are new or whose title or text changed, in one statement that replaces a row of the same
    stock and key, so two saves of the same article at once keep one row. In the same transaction it drops every
    article published more than `retention` ago, of any stock, and each named stock's oldest beyond `max_per_stock`.
    An article's publication time is answered in the exchange's zone.
    """

    def __init__(self, db: DatabaseConnector, market_clock: IMarketClock, retention: timedelta, max_per_stock: int) -> None:
        self._db = db
        self._market_clock = market_clock
        self._retention = retention
        self._max_per_stock = max_per_stock

    @override
    async def save(self, articles: Sequence[Article]) -> int:
        now = self._market_clock.now()
        given = {(article.stock_id, article.key): article for article in articles if article.published_at >= now - self._retention}
        stock_ids = sorted({stock_id for stock_id, _ in given})
        newest_first = col(StoredArticleDTO.published_at).desc()

        async with self._db.get_session() as session:
            held = (await session.execute(select(StoredArticleDTO).where(col(StoredArticleDTO.stock_id).in_(stock_ids)))).scalars()
            kept = {(row.stock_id, row.key): (row.title, row.content) for row in held}
            changed = [article for place, article in given.items() if kept.get(place) != (article.title, article.content)]

            if changed:
                rows = [StoredArticleDTO.from_domain(article, now).model_dump() for article in changed]
                await session.execute(replacing(StoredArticleDTO), rows)

            await session.execute(delete(StoredArticleDTO).where(col(StoredArticleDTO.published_at) < now - self._retention))

            for stock_id in stock_ids:
                of_stock = col(StoredArticleDTO.stock_id) == stock_id
                beyond = select(StoredArticleDTO.key).where(of_stock).order_by(newest_first).offset(self._max_per_stock)
                surplus = (await session.execute(beyond)).scalars().all()
                await session.execute(delete(StoredArticleDTO).where(of_stock, col(StoredArticleDTO.key).in_(surplus)))

            await session.commit()

        return len(changed)

    @override
    async def latest(self, stock_id: str, limit: int) -> list[Article]:
        newest_first = (
            select(StoredArticleDTO)
            .where(col(StoredArticleDTO.stock_id) == stock_id)
            .order_by(col(StoredArticleDTO.published_at).desc(), col(StoredArticleDTO.key))
            .limit(limit)
        )

        async with self._db.get_session() as session:
            rows = (await session.execute(newest_first)).scalars().all()

        return [row.to_domain(self._market_clock.to_market_datetime(row.published_at)) for row in rows]

    @override
    async def find(self, stock_id: str, keys: Collection[str]) -> list[Article]:
        named = select(StoredArticleDTO).where(col(StoredArticleDTO.stock_id) == stock_id, col(StoredArticleDTO.key).in_(keys))

        async with self._db.get_session() as session:
            rows = (await session.execute(named)).scalars().all()

        return [row.to_domain(self._market_clock.to_market_datetime(row.published_at)) for row in rows]

    @override
    async def stock_ids(self) -> list[str]:
        distinct = select(StoredArticleDTO.stock_id).distinct().order_by(col(StoredArticleDTO.stock_id))

        async with self._db.get_session() as session:
            return list((await session.execute(distinct)).scalars().all())
