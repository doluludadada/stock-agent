# backend/src/c_infrastructure/database/repositories/watchlist_repository.py

from sqlalchemy import or_
from sqlmodel import col, delete, select

from a_domain.model.trading.watchlist import WatchlistEntry
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.system.market_clock import IMarketClock
from a_domain.ports.trading.watchlist_repository import IWatchlistRepository
from a_domain.types.enums import WatchlistType
from c_infrastructure.database.db_connector import DatabaseConnector
from c_infrastructure.database.models.watchlist_dto import WatchlistDTO


class WatchlistRepository(IWatchlistRepository):
    def __init__(self, db: DatabaseConnector, logger: ILoggingProvider, market_clock: IMarketClock) -> None:
        self._db = db
        self._logger = logger
        self._market_clock = market_clock

    async def get_active(self) -> list[WatchlistEntry]:
        now = self._market_clock.now()

        async with self._db.get_session() as session:
            statement = select(WatchlistDTO).where(or_(col(WatchlistDTO.expires_at).is_(None), col(WatchlistDTO.expires_at) > now))
            result = await session.execute(statement)
            rows = result.scalars().all()

        return [self._to_entry(row) for row in rows]

    async def save(self, entries: list[WatchlistEntry]) -> None:
        if not entries:
            return

        async with self._db.get_session() as session:
            for entry in entries:
                await session.merge(
                    WatchlistDTO(
                        stock_id=entry.stock_id, type=entry.watchlist_type, created_at=entry.created_at, expires_at=entry.expires_at
                    )
                )

            await session.commit()

        self._logger.debug(f"Saved {len(entries)} watchlist entries.")

    async def remove(self, stock_id: str) -> None:
        async with self._db.get_session() as session:
            statement = delete(WatchlistDTO).where(col(WatchlistDTO.stock_id) == stock_id)
            await session.execute(statement)
            await session.commit()

        self._logger.debug(f"Removed {stock_id} from watchlist.")

    def _to_entry(self, row: WatchlistDTO) -> WatchlistEntry:
        # SQLite drops the UTC offset, so stored times are read back as market time.
        return WatchlistEntry(
            stock_id=row.stock_id,
            watchlist_type=WatchlistType(row.type),
            created_at=self._market_clock.to_market_datetime(row.created_at),
            expires_at=self._market_clock.to_market_datetime(row.expires_at) if row.expires_at is not None else None,
        )
