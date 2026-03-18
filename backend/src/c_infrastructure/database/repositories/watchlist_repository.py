# backend/src/c_infrastructure/database/repositories/watchlist_repository.py
from datetime import datetime, timedelta

from sqlmodel import delete, select

from a_domain.model.market.stock import Stock
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.trading.watchlist_repository import IWatchlistRepository
from a_domain.types.enums import CandidateSource
from c_infrastructure.database.db_connector import DatabaseConnector
from c_infrastructure.database.models.watchlist_dto import WatchlistDTO


class WatchlistRepository(IWatchlistRepository):
    def __init__(self, db: DatabaseConnector, logger: ILoggingProvider):
        self._db = db
        self._logger = logger

    async def get_technical_watchlist(self) -> list[Stock]:
        cutoff = datetime.now() - timedelta(hours=24)

        async with self._db.get_session() as session:
            stmt = select(WatchlistDTO).where(
                WatchlistDTO.list_type == CandidateSource.TECHNICAL_WATCHLIST, WatchlistDTO.created_at >= cutoff
            )
            result = await session.execute(stmt)
            dtos = result.scalars().all()
            return [Stock(stock_id=dto.stock_id, source=CandidateSource.TECHNICAL_WATCHLIST) for dto in dtos]

    async def save_technical_watchlist(self, stocks: list[Stock]) -> None:
        async with self._db.get_session() as session:
            cutoff = datetime.now() - timedelta(hours=24)
            # FIX 3: Use .value
            await session.execute(
                delete(WatchlistDTO).where(
                    WatchlistDTO.list_type == CandidateSource.TECHNICAL_WATCHLIST, # type: ignore
                    WatchlistDTO.created_at >= cutoff, # type: ignore
                )
            )

            for stock in stocks:
                dto = WatchlistDTO(
                    stock_id=stock.stock_id,
                    list_type=CandidateSource.TECHNICAL_WATCHLIST,
                    reason=stock.trigger_reason or "Nightly Screen",
                )
                session.add(dto)

            await session.commit()
            self._logger.debug(f"Persisted {len(stocks)} stocks to Technical Watchlist in DB.")

    async def get_buzz_watchlist(self) -> list[tuple[Stock, str]]:
        cutoff = datetime.now() - timedelta(hours=24)
        async with self._db.get_session() as session:
            stmt = select(WatchlistDTO).where(
                WatchlistDTO.list_type == CandidateSource.SOCIAL_BUZZ.value, WatchlistDTO.created_at >= cutoff
            )
            result = await session.execute(stmt)
            dtos = result.scalars().all()
            return [(Stock(stock_id=dto.stock_id, source=CandidateSource.SOCIAL_BUZZ), dto.reason) for dto in dtos]

    async def save_buzz_watchlist(self, stocks: list[Stock], reasons: list[str]) -> None:
        async with self._db.get_session() as session:
            for stock, reason in zip(stocks, reasons):
                dto = WatchlistDTO(stock_id=stock.stock_id, list_type=CandidateSource.SOCIAL_BUZZ.value, reason=reason)
                session.add(dto)
            await session.commit()

    async def get_stocks_by_ids(self, stock_ids: list[str]) -> list[Stock]:
        return [Stock(stock_id=sid, source=CandidateSource.MANUAL_INPUT) for sid in stock_ids]
