from sqlalchemy import or_
from sqlmodel import col, delete, select

from a_domain.model.market.stock import Stock
from a_domain.model.trading.watchlist import StockWatchlist
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.system.market_clock import IMarketClock
from a_domain.ports.trading.watchlist_repository import IWatchlistRepository
from a_domain.rules.trading.watchlist import WatchlistRule
from a_domain.types.enums import WatchlistType
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

    async def get_active(self) -> StockWatchlist:
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

        watchlist = StockWatchlist()
        for row in rows:
            watchlist_type = WatchlistType(row.type)
            watchlist.add(
                Stock(
                    stock_id=row.stock_id,
                    candidate_source=watchlist_type,
                )
            )

        return watchlist

    async def upsert(
        self,
        entries: StockWatchlist,
    ) -> None:
        if not entries.willing_stocks:
            return

        async with self._db.get_session() as session:
            for stock in entries.willing_stocks:
                watchlist_type = stock.candidate_source or WatchlistType.TECHNICAL
                existing = await session.get(
                    WatchlistDTO,
                    stock.stock_id,
                )

                if existing is None:
                    session.add(
                        WatchlistDTO(
                            stock_id=stock.stock_id,
                            type=watchlist_type,
                            created_at=entries.created_at,
                            expires_at=entries.expires_at,
                        )
                    )
                    continue

                existing.type = self._watchlist_rule.merge(
                    current=WatchlistType(existing.type),
                    incoming=watchlist_type,
                )
                existing.created_at = entries.created_at
                existing.expires_at = entries.expires_at

            await session.commit()

        self._logger.debug(f"Persisted {len(entries.willing_stocks)} watchlist entries.")

    async def remove(
        self,
        stock_id: str,
    ) -> None:
        async with self._db.get_session() as session:
            statement = delete(WatchlistDTO).where(col(WatchlistDTO.stock_id) == stock_id)

            await session.execute(statement)
            await session.commit()

        self._logger.debug(f"Removed {stock_id} from watchlist.")
