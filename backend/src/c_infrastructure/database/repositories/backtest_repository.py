from typing import override

from sqlalchemy import delete
from sqlmodel import col, select

from a_domain.model.trading.backtest import Backtest
from a_domain.ports.trading.backtest_repository import IBacktestRepository
from a_domain.types.ids import BacktestId
from c_infrastructure.database.db_connector import DatabaseConnector
from c_infrastructure.database.models.backtest_dto import BacktestDTO


class SqlBacktestRepository(IBacktestRepository):
    """One owner's rows of the backtests table, through a connector bound to that owner."""

    def __init__(self, db: DatabaseConnector) -> None:
        self._db = db

    @override
    async def save(self, backtest: Backtest, keep: int) -> None:
        older = select(col(BacktestDTO.backtest_id)).order_by(col(BacktestDTO.created_at).desc()).offset(keep)

        async with self._db.owner_session() as session:
            session.add(BacktestDTO.from_domain(backtest, self._db.owner_id))
            await session.flush()
            dropped = (await session.execute(older)).scalars().all()

            if dropped:
                await session.execute(delete(BacktestDTO).where(col(BacktestDTO.backtest_id).in_(dropped)))

            await session.commit()

    @override
    async def saved(self) -> list[Backtest]:
        newest_first = select(BacktestDTO).order_by(col(BacktestDTO.created_at).desc())

        async with self._db.owner_session() as session:
            return [row.to_domain() for row in (await session.execute(newest_first)).scalars().all()]

    @override
    async def get(self, backtest_id: BacktestId) -> Backtest | None:
        one = select(BacktestDTO).where(col(BacktestDTO.backtest_id) == backtest_id)

        async with self._db.owner_session() as session:
            row = (await session.execute(one)).scalar_one_or_none()

        return row.to_domain() if row is not None else None

    @override
    async def delete(self, backtest_id: BacktestId) -> bool:
        one = delete(BacktestDTO).where(col(BacktestDTO.backtest_id) == backtest_id).returning(col(BacktestDTO.backtest_id))

        async with self._db.owner_session() as session:
            deleted = (await session.execute(one)).scalar_one_or_none()
            await session.commit()

        return deleted is not None
