# backend/src/c_infrastructure/database/repositories/watchlist_repository.py

from datetime import timedelta

from sqlmodel import col, delete, select

from a_domain.model.market.stock import Stock
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.system.market_clock import IMarketClock
from a_domain.ports.trading.watchlist_repository import IWatchlistRepository
from a_domain.types.enums import CandidateSource, MarketType
from c_infrastructure.database.db_connector import DatabaseConnector
from c_infrastructure.database.models.watchlist_dto import WatchlistDTO


class WatchlistRepository(IWatchlistRepository):
    def __init__(
        self,
        db: DatabaseConnector,
        logger: ILoggingProvider,
        market_clock: IMarketClock,
    ):
        self._db = db
        self._logger = logger
        self._clock = market_clock

    async def get_technical_watchlist(self) -> list[Stock]:
        cutoff = self._clock.now() - timedelta(hours=24)

        async with self._db.get_session() as session:
            stmt = select(WatchlistDTO).where(
                col(WatchlistDTO.list_type) == CandidateSource.TECHNICAL_WATCHLIST.value,
                col(WatchlistDTO.created_at) >= cutoff,
            )
            result = await session.execute(stmt)
            rows = result.scalars().all()

        return [
            Stock(
                stock_id=row.stock_id,
                market=self._safe_market(row.market),
                name=row.name,
                source=CandidateSource.TECHNICAL_WATCHLIST,
                trigger_reason=row.reason,
            )
            for row in rows
        ]

    async def save_technical_watchlist(self, stocks: list[Stock]) -> None:
        cutoff = self._clock.now() - timedelta(hours=24)

        async with self._db.get_session() as session:
            await session.execute(
                delete(WatchlistDTO).where(
                    col(WatchlistDTO.list_type) == CandidateSource.TECHNICAL_WATCHLIST.value,
                    col(WatchlistDTO.created_at) >= cutoff,
                )
            )

            for stock in stocks:
                session.add(
                    WatchlistDTO(
                        stock_id=stock.stock_id,
                        market=stock.market.value,
                        name=stock.name,
                        list_type=CandidateSource.TECHNICAL_WATCHLIST.value,
                        reason=stock.trigger_reason or "Nightly Technical Screen",
                        created_at=self._clock.now(),
                    )
                )

            await session.commit()

        self._logger.debug(f"Persisted {len(stocks)} stocks to Technical Watchlist in DB.")

    async def get_buzz_watchlist(self) -> list[tuple[Stock, str]]:
        cutoff = self._clock.now() - timedelta(hours=24)

        async with self._db.get_session() as session:
            stmt = select(WatchlistDTO).where(
                col(WatchlistDTO.list_type) == CandidateSource.SOCIAL_BUZZ.value,
                col(WatchlistDTO.created_at) >= cutoff,
            )
            result = await session.execute(stmt)
            rows = result.scalars().all()

        return [
            (
                Stock(
                    stock_id=row.stock_id,
                    market=self._safe_market(row.market),
                    name=row.name,
                    source=CandidateSource.SOCIAL_BUZZ,
                    trigger_reason=row.reason,
                ),
                row.reason,
            )
            for row in rows
        ]

    async def save_buzz_watchlist(self, stocks: list[Stock], reasons: list[str]) -> None:
        cutoff = self._clock.now() - timedelta(hours=24)

        async with self._db.get_session() as session:
            await session.execute(
                delete(WatchlistDTO).where(
                    col(WatchlistDTO.list_type) == CandidateSource.SOCIAL_BUZZ.value,
                    col(WatchlistDTO.created_at) >= cutoff,
                )
            )

            for stock, reason in zip(stocks, reasons, strict=True):
                session.add(
                    WatchlistDTO(
                        stock_id=stock.stock_id,
                        market=stock.market.value,
                        name=stock.name,
                        list_type=CandidateSource.SOCIAL_BUZZ.value,
                        reason=reason,
                        created_at=self._clock.now(),
                    )
                )

            await session.commit()

        self._logger.debug(f"Persisted {len(stocks)} stocks to Buzz Watchlist in DB.")

    async def get_stocks_by_ids(self, stock_ids: list[str]) -> list[Stock]:
        return [
            Stock(
                stock_id=stock_id,
                source=CandidateSource.MANUAL_INPUT,
                trigger_reason="User Manual Request",
            )
            for stock_id in stock_ids
        ]

    def _safe_market(self, value: str) -> MarketType:
        try:
            return MarketType(value)
        except ValueError:
            self._logger.warning(f"Unknown market value in watchlist row: {value}. Fallback to TWSE.")
            return MarketType.TWSE
