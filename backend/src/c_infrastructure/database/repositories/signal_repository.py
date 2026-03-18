# backend/src/c_infrastructure/database/repositories/signal_repository.py
from datetime import datetime

from sqlmodel import select

from a_domain.model.trading.signal import TradeSignal
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.trading.signal_repository import ISignalRepository
from c_infrastructure.database.db_connector import DatabaseConnector
from c_infrastructure.database.models.trade_signal_dto import TradeSignalDTO


class SignalRepository(ISignalRepository):
    def __init__(self, db: DatabaseConnector, logger: ILoggingProvider):
        self._db = db
        self._logger = logger

    async def save(self, signal: TradeSignal) -> None:
        async with self._db.get_session() as session:
            dto = TradeSignalDTO.model_validate(signal)
            session.add(dto)
            await session.commit()

    async def save_batch(self, signals: list[TradeSignal]) -> None:
        async with self._db.get_session() as session:
            for signal in signals:
                dto = TradeSignalDTO.model_validate(signal)
                session.add(dto)
            await session.commit()
            self._logger.debug(f"Persisted {len(signals)} trade signals to DB.")

    async def get_by_stock_id(
        self, stock_id: str, start_date: datetime | None = None, limit: int = 10
    ) -> list[TradeSignal]:
        async with self._db.get_session() as session:
            stmt = select(TradeSignalDTO).where(TradeSignalDTO.stock_id == stock_id)
            if start_date:
                stmt = stmt.where(TradeSignalDTO.generated_at >= start_date)
            stmt = stmt.order_by(TradeSignalDTO.generated_at.desc()).limit(limit)  # type: ignore

            result = await session.execute(stmt)
            dtos = result.scalars().all()
            return [TradeSignal.model_validate(dto) for dto in dtos]

    async def get_latest(self, limit: int = 50) -> list[TradeSignal]:
        async with self._db.get_session() as session:
            stmt = select(TradeSignalDTO).order_by(TradeSignalDTO.generated_at.desc()).limit(limit)  # type: ignore
            result = await session.execute(stmt)
            dtos = result.scalars().all()
            return [TradeSignal.model_validate(dto) for dto in dtos]
