from collections.abc import Collection, Mapping, Sequence
from datetime import datetime, timedelta
from typing import override

from sqlalchemy import Delete, delete
from sqlmodel import col, select
from sqlmodel.sql.expression import SelectOfScalar

from a_domain.model.market.article import Article
from a_domain.ports.market.article_store import IArticleStore
from a_domain.ports.system.market_clock import IMarketClock
from a_domain.types.enums import InformationSource
from c_infrastructure.database.db_connector import DatabaseConnector
from c_infrastructure.database.models.article_store_dto import StoredArticleDTO
from c_infrastructure.database.upsert import replacing


class SqlArticleStore(IArticleStore):
    """
    The stored_articles table, shared by every user. A save reads what the table holds of the stocks named and writes
    only the articles that are new or whose title or text changed, in one statement that replaces a row of the same
    stock and key, so two saves of the same article at once keep one row. In the same transaction it drops every
    article published more than `retention` ago, of any stock, and each named stock's oldest beyond `max_per_stock`,
    which a document of record does not count toward (InformationSource.is_reference).
    A key that is no stock's, such as the world news', is named in `own_bounds` with a retention and a most of its
    own, which hold for it in place of `max_per_stock` and within `retention`; it is no stock of stock_ids.
    An article's publication time is answered in the exchange's zone.
    """

    def __init__(
        self,
        db: DatabaseConnector,
        market_clock: IMarketClock,
        retention: timedelta,
        max_per_stock: int,
        own_bounds: Mapping[str, tuple[timedelta, int]],
    ) -> None:
        self._db = db
        self._market_clock = market_clock
        self._retention = retention
        self._max_per_stock = max_per_stock
        self._own_bounds = own_bounds

    @override
    async def save(self, articles: Sequence[Article]) -> int:
        now = self._market_clock.now()
        bounds = {
            article.stock_id: self._own_bounds.get(article.stock_id, (self._retention, self._max_per_stock)) for article in articles
        }
        since = {stock_id: now - min(retention, self._retention) for stock_id, (retention, _) in bounds.items()}
        given = {(article.stock_id, article.key): article for article in articles if article.published_at >= since[article.stock_id]}
        stock_ids = sorted({stock_id for stock_id, _ in given})

        async with self._db.get_session() as session:
            held = (await session.execute(select(StoredArticleDTO).where(col(StoredArticleDTO.stock_id).in_(stock_ids)))).scalars()
            kept = {(row.stock_id, row.key): (row.title, row.content) for row in held}
            changed = [article for place, article in given.items() if kept.get(place) != (article.title, article.content)]

            if changed:
                rows = [StoredArticleDTO.from_domain(article, now).model_dump() for article in changed]
                await session.execute(replacing(StoredArticleDTO), rows)

            await session.execute(delete(StoredArticleDTO).where(col(StoredArticleDTO.published_at) < now - self._retention))

            for stock_id in stock_ids:
                await session.execute(published_before(stock_id, since[stock_id]))
                surplus = (await session.execute(beyond(stock_id, bounds[stock_id][1]))).scalars().all()
                of_stock = col(StoredArticleDTO.stock_id) == stock_id
                await session.execute(delete(StoredArticleDTO).where(of_stock, col(StoredArticleDTO.key).in_(surplus)))

            await session.commit()

        return len(changed)

    @override
    async def latest(self, stock_id: str, limit: int) -> list[Article]:
        newest_first = (
            select(StoredArticleDTO)
            .where(col(StoredArticleDTO.stock_id) == stock_id, col(StoredArticleDTO.source).not_in(reference_sources()))
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
    async def references(self, stock_id: str) -> list[Article]:
        kept = select(StoredArticleDTO).where(
            col(StoredArticleDTO.stock_id) == stock_id, col(StoredArticleDTO.source).in_(reference_sources())
        )

        async with self._db.get_session() as session:
            rows = (await session.execute(kept)).scalars().all()

        return [row.to_domain(self._market_clock.to_market_datetime(row.published_at)) for row in rows]

    @override
    async def stock_ids(self) -> list[str]:
        of_a_stock = col(StoredArticleDTO.stock_id).not_in(list(self._own_bounds))
        distinct = select(StoredArticleDTO.stock_id).where(of_a_stock).distinct().order_by(col(StoredArticleDTO.stock_id))

        async with self._db.get_session() as session:
            return list((await session.execute(distinct)).scalars().all())


def published_before(stock_id: str, instant: datetime) -> Delete:
    """The removal of the key's articles published before `instant`: what its own retention no longer keeps."""
    return delete(StoredArticleDTO).where(col(StoredArticleDTO.stock_id) == stock_id, col(StoredArticleDTO.published_at) < instant)


def beyond(stock_id: str, most: int) -> SelectOfScalar[str]:
    """The keys of the key's news beyond its newest `most`; a document of record is no news and is never among them."""
    daily = col(StoredArticleDTO.source).not_in(reference_sources())
    newest_first = col(StoredArticleDTO.published_at).desc()
    return select(StoredArticleDTO.key).where(col(StoredArticleDTO.stock_id) == stock_id, daily).order_by(newest_first).offset(most)


def reference_sources() -> list[str]:
    """The sources of documents of record, as the table stores them."""
    return [source.value for source in InformationSource if source.is_reference]
