from typing import override

from sqlalchemy import delete, or_
from sqlmodel import col, select

from a_domain.model.trading.watchlist import WatchlistEntry
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.system.market_clock import IMarketClock
from a_domain.ports.trading.watchlist_repository import IWatchlistRepository
from a_domain.types.enums import WatchlistType
from c_infrastructure.database.db_connector import DatabaseConnector
from c_infrastructure.database.models.watchlist_dto import WatchlistDTO


class WatchlistRepository(IWatchlistRepository):
    """
    One owner's watchlist, through a connector bound to that owner: another owner's entries are neither read nor
    removed.
    """

    def __init__(self, db: DatabaseConnector, logger: ILoggingProvider, market_clock: IMarketClock) -> None:
        self._db = db
        self._logger = logger
        self._market_clock = market_clock

    @override
    async def get_active(self) -> list[WatchlistEntry]:
        now = self._market_clock.now()

        async with self._db.owner_session() as session:
            statement = select(WatchlistDTO).where(or_(col(WatchlistDTO.expires_at).is_(None), col(WatchlistDTO.expires_at) > now))
            result = await session.execute(statement)
            rows = result.scalars().all()

        return [
            WatchlistEntry(
                stock_id=row.stock_id, watchlist_type=WatchlistType(row.type), created_at=row.created_at, expires_at=row.expires_at
            )
            for row in rows
        ]

    @override
    async def save(self, entries: list[WatchlistEntry]) -> None:
        if not entries:
            return

        async with self._db.owner_session() as session:
            for entry in entries:
                await session.merge(
                    WatchlistDTO(
                        owner_id=self._db.owner_id,
                        stock_id=entry.stock_id,
                        type=entry.watchlist_type,
                        created_at=entry.created_at,
                        expires_at=entry.expires_at,
                    )
                )

            await session.commit()

        self._logger.debug(f"Saved {len(entries)} watchlist entries.")

    @override
    async def remove(self, stock_ids: list[str], watchlist_type: WatchlistType) -> list[str]:
        if not stock_ids:
            return []

        matching = (col(WatchlistDTO.stock_id).in_(stock_ids), col(WatchlistDTO.type) == watchlist_type)

        async with self._db.owner_session() as session:
            present = list((await session.execute(select(WatchlistDTO.stock_id).where(*matching))).scalars())
            await session.execute(delete(WatchlistDTO).where(*matching))
            await session.commit()

        self._logger.debug(f"Removed {len(present)} {watchlist_type.value} watchlist entries.")

        return [stock_id for stock_id in stock_ids if stock_id in present]
