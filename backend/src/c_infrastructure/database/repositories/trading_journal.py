from dataclasses import asdict
from typing import override

from pydantic import TypeAdapter
from sqlalchemy import delete
from sqlmodel import col, select

from a_domain.model.market.stock import Stock
from a_domain.model.system.stats import SystemStats
from a_domain.model.trading.account import AccountSnapshot
from a_domain.model.trading.order import Order
from a_domain.model.trading.signal import TradeSignal
from a_domain.ports.trading.trading_journal import ITradingJournal
from a_domain.types.ids import RunId
from c_infrastructure.database.db_connector import DatabaseConnector
from c_infrastructure.database.models.trading_journal_dto import (
    AccountSnapshotDTO,
    OrderDTO,
    RunStockReportDTO,
    TradeSignalDTO,
    WorkflowRunDTO,
)


class TradingJournal(ITradingJournal):
    """
    SQL tables workflow_runs, trade_signals, orders, account_snapshots and run_stock_reports. Every save is an upsert
    by primary key.
    """

    def __init__(self, db: DatabaseConnector) -> None:
        self._db = db
        self._signal = TypeAdapter(TradeSignal)

    @override
    async def save_run(self, run: SystemStats) -> None:
        async with self._db.get_session() as session:
            await session.merge(WorkflowRunDTO.model_validate(asdict(run)))
            await session.commit()

    @override
    async def save_signals(self, run_id: RunId, signals: list[TradeSignal]) -> None:
        async with self._db.get_session() as session:
            for signal in signals:
                reports = self._signal.dump_python(signal, mode="json", include={"technical_report", "ai_report"})
                await session.merge(TradeSignalDTO.model_validate({**asdict(signal), **reports, "run_id": run_id}))

            await session.commit()

    @override
    async def save_order(self, order: Order) -> None:
        async with self._db.get_session() as session:
            await session.merge(OrderDTO.model_validate(asdict(order)))
            await session.commit()

    @override
    async def save_snapshot(self, snapshot: AccountSnapshot) -> None:
        async with self._db.get_session() as session:
            await session.merge(AccountSnapshotDTO.from_domain(snapshot))
            await session.commit()

    @override
    async def snapshots(self) -> list[AccountSnapshot]:
        async with self._db.get_session() as session:
            result = await session.execute(select(AccountSnapshotDTO).order_by(col(AccountSnapshotDTO.taken_at)))
            rows = result.scalars().all()

        return [row.to_domain() for row in rows]

    @override
    async def save_stock_reports(self, run_id: RunId, stocks: list[Stock]) -> None:
        async with self._db.get_session() as session:
            await session.execute(delete(RunStockReportDTO).where(col(RunStockReportDTO.run_id) == run_id))

            for position, stock in enumerate(stocks):
                session.add(RunStockReportDTO.from_domain(run_id, position, stock))

            await session.commit()

    @override
    async def stock_reports_of(self, run_id: RunId) -> list[Stock]:
        async with self._db.get_session() as session:
            statement = (
                select(RunStockReportDTO).where(col(RunStockReportDTO.run_id) == run_id).order_by(col(RunStockReportDTO.position))
            )
            rows = (await session.execute(statement)).scalars().all()

        return [row.to_domain() for row in rows]

    @override
    async def recent_runs(self, limit: int, offset: int = 0) -> list[SystemStats]:
        async with self._db.get_session() as session:
            statement = select(WorkflowRunDTO).order_by(col(WorkflowRunDTO.start_time).desc()).offset(offset).limit(limit)
            rows = (await session.execute(statement)).scalars().all()

        return [SystemStats(**row.model_dump()) for row in rows]

    @override
    async def find_run(self, run_id: RunId) -> SystemStats | None:
        async with self._db.get_session() as session:
            row = await session.get(WorkflowRunDTO, run_id)

        return SystemStats(**row.model_dump()) if row is not None else None

    @override
    async def signals_of(self, run_id: RunId) -> list[TradeSignal]:
        async with self._db.get_session() as session:
            statement = select(TradeSignalDTO).where(col(TradeSignalDTO.run_id) == run_id).order_by(col(TradeSignalDTO.generated_at))
            rows = (await session.execute(statement)).scalars().all()

        return [TradeSignal(**row.model_dump(exclude={"run_id"})) for row in rows]

    @override
    async def orders_of(self, run_id: RunId) -> list[Order]:
        async with self._db.get_session() as session:
            statement = select(OrderDTO).where(col(OrderDTO.run_id) == run_id).order_by(col(OrderDTO.created_at))
            rows = (await session.execute(statement)).scalars().all()

        return [Order(**row.model_dump()) for row in rows]
