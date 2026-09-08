# backend/src/c_infrastructure/database/repositories/watchlist_repository.py

from sqlalchemy import or_
from sqlmodel import col, delete, select

from a_domain.model.market.stock import Stock
from a_domain.model.trading.watchlist import StockWatchlist
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.system.market_clock import IMarketClock
from a_domain.ports.trading.watchlist_repository import IWatchlistRepository
from a_domain.types.enums import WatchlistType
from c_infrastructure.database.db_connector import DatabaseConnector
from c_infrastructure.database.models.watchlist_dto import WatchlistDTO


class WatchlistRepository(IWatchlistRepository):
    def __init__(
        self,
        db: DatabaseConnector,
        logger: ILoggingProvider,
        market_clock: IMarketClock,
    ) -> None:
        self._db = db
        self._logger = logger
        self._market_clock = market_clock

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

        stocks_by_id: dict[str, Stock] = {}

        for row in rows:
            stock = stocks_by_id.setdefault(
                row.stock_id,
                Stock(stock_id=row.stock_id),
            )
            stock.watchlist_types.add(WatchlistType(row.type))

        return StockWatchlist(willing_stocks=list(stocks_by_id.values()))

    async def add(
        self,
        stocks: list[Stock],
        watchlist_type: WatchlistType,
    ) -> StockWatchlist:
        unique_stocks = {stock.stock_id: stock for stock in stocks}

        for stock in unique_stocks.values():
            stock.watchlist_types.add(watchlist_type)

        watchlist = StockWatchlist(willing_stocks=list(unique_stocks.values()))

        if not unique_stocks:
            return watchlist

        async with self._db.get_session() as session:
            statement = select(WatchlistDTO.stock_id).where(
                col(WatchlistDTO.stock_id).in_(unique_stocks),
                WatchlistDTO.type == watchlist_type,
            )
            result = await session.execute(statement)
            existing_stock_ids = set(result.scalars().all())

            for stock_id in unique_stocks.keys() - existing_stock_ids:
                session.add(
                    WatchlistDTO(
                        stock_id=stock_id,
                        type=watchlist_type,
                        created_at=watchlist.created_at,
                    )
                )

            await session.commit()

        self._logger.debug(f"Added {len(unique_stocks)} {watchlist_type.value} watchlist stocks.")
        return watchlist

    async def remove(self, stock_id: str) -> None:
        async with self._db.get_session() as session:
            statement = delete(WatchlistDTO).where(col(WatchlistDTO.stock_id) == stock_id)
            await session.execute(statement)
            await session.commit()

        self._logger.debug(f"Removed {stock_id} from watchlist.")
