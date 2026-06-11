from sqlalchemy import or_
from sqlmodel import col, delete, select

from a_domain.model.trading.watchlist import StockWatchlist
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.system.market_clock import IMarketClock
from a_domain.ports.trading.watchlist_repository import IWatchlistRepository
from a_domain.rules.trading.watchlist import WatchlistRule
from c_infrastructure.database.db_connector import DatabaseConnector
from c_infrastructure.database.models.watchlist_dto import WatchlistDTO


class WatchlistRepository(IWatchlistRepository):
    def __init__(
        self,
        db: DatabaseConnector,
        logger: ILoggingProvider,
        market_clock: IMarketClock,
        watchlist_rule: WatchlistRule,
    ) -> None:
        self._db = db
        self._logger = logger
        self._market_clock = market_clock
        self._watchlist_rule = watchlist_rule

    async def get_active(self) -> list[StockWatchlist]:
        now = self._market_clock.now()

        async with self._db.get_session() as session:
            statement = select(WatchlistDTO).where(
                or_(
                    col(WatchlistDTO.expires_at).is_(None),
                    col(WatchlistDTO.expires_at) > now,
                )
            )

            result = await session.execute(statement)
            rows = result.scalars().all()

        return [StockWatchlist.model_validate(row) for row in rows]

    async def upsert(
        self,
        entries: list[StockWatchlist],
    ) -> None:
        if not entries:
            return

        async with self._db.get_session() as session:
            for entry in entries:
                existing = await session.get(
                    WatchlistDTO,
                    entry.stock_id,
                )

                if existing is None:
                    session.add(WatchlistDTO.model_validate(entry))
                    continue

                existing.type = self._watchlist_rule.merge(
                    current=existing.type,
                    incoming=entry.type,
                )
                existing.created_at = entry.created_at
                existing.expires_at = entry.expires_at

            await session.commit()

        self._logger.debug(f"Persisted {len(entries)} watchlist entries.")

    async def remove(
        self,
        stock_id: str,
    ) -> None:
        async with self._db.get_session() as session:
            statement = delete(WatchlistDTO).where(col(WatchlistDTO.stock_id) == stock_id)

            await session.execute(statement)
            await session.commit()

        self._logger.debug(f"Removed {stock_id} from watchlist.")
