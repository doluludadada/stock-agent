from dataclasses import asdict
from datetime import datetime
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
from a_domain.types.enums import ExecutionProvider, TradeAction, Workflow
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
    One owner's rows of the SQL tables workflow_runs, trade_signals, orders, account_snapshots and run_stock_reports,
    through a connector bound to that owner. Every save is an upsert by primary key and stamps the owner; the owner
    session keeps every read and write to the owner's rows, so a run id of another owner reads as no run.
    """

    def __init__(self, db: DatabaseConnector) -> None:
        self._db = db
        self._signal = TypeAdapter(TradeSignal)

    @override
    async def save_run(self, run: SystemStats) -> None:
        async with self._db.owner_session() as session:
            await session.merge(WorkflowRunDTO.model_validate({**asdict(run), "owner_id": self._db.owner_id}))
            await session.commit()

    @override
    async def save_signals(self, run_id: RunId, signals: list[TradeSignal]) -> None:
        async with self._db.owner_session() as session:
            for signal in signals:
                reports = self._signal.dump_python(signal, mode="json", include={"technical_report", "ai_report"})
                await session.merge(
                    TradeSignalDTO.model_validate({**asdict(signal), **reports, "run_id": run_id, "owner_id": self._db.owner_id})
                )

            await session.commit()

    @override
    async def save_order(self, order: Order) -> None:
        async with self._db.owner_session() as session:
            await session.merge(OrderDTO.model_validate({**asdict(order), "owner_id": self._db.owner_id}))
            await session.commit()

    @override
    async def save_snapshot(self, snapshot: AccountSnapshot) -> None:
        async with self._db.owner_session() as session:
            await session.merge(AccountSnapshotDTO.from_domain(snapshot, self._db.owner_id))
            await session.commit()

    @override
    async def snapshots(self, broker: ExecutionProvider, since: datetime | None = None) -> list[AccountSnapshot]:
        statement = (
            select(AccountSnapshotDTO)
            .join(WorkflowRunDTO, col(WorkflowRunDTO.run_id) == col(AccountSnapshotDTO.run_id))
            .where(col(WorkflowRunDTO.execution_provider) == broker)
            .order_by(col(AccountSnapshotDTO.taken_at))
        )

        if since is not None:
            statement = statement.where(col(AccountSnapshotDTO.taken_at) >= since)

        async with self._db.owner_session() as session:
            rows = (await session.execute(statement)).scalars().all()

        return [row.to_domain() for row in rows]

    @override
    async def save_stock_reports(self, run_id: RunId, stocks: list[Stock]) -> None:
        async with self._db.owner_session() as session:
            await session.execute(delete(RunStockReportDTO).where(col(RunStockReportDTO.run_id) == run_id))

            for position, stock in enumerate(stocks):
                session.add(RunStockReportDTO.from_domain(run_id, position, stock, self._db.owner_id))

            await session.commit()

    @override
    async def stock_reports_of(self, run_id: RunId) -> list[Stock]:
        async with self._db.owner_session() as session:
            statement = (
                select(RunStockReportDTO).where(col(RunStockReportDTO.run_id) == run_id).order_by(col(RunStockReportDTO.position))
            )
            rows = (await session.execute(statement)).scalars().all()

        return [row.to_domain() for row in rows]

    @override
    async def recent_runs(self, limit: int, offset: int = 0) -> list[SystemStats]:
        async with self._db.owner_session() as session:
            statement = select(WorkflowRunDTO).order_by(col(WorkflowRunDTO.start_time).desc()).offset(offset).limit(limit)
            rows = (await session.execute(statement)).scalars().all()

        return [SystemStats(**row.model_dump()) for row in rows]

    @override
    async def find_run(self, run_id: RunId) -> SystemStats | None:
        async with self._db.owner_session() as session:
            row = await session.get(WorkflowRunDTO, run_id)

        return SystemStats(**row.model_dump()) if row is not None else None

    @override
    async def signals_of(self, run_id: RunId) -> list[TradeSignal]:
        async with self._db.owner_session() as session:
            statement = select(TradeSignalDTO).where(col(TradeSignalDTO.run_id) == run_id).order_by(col(TradeSignalDTO.generated_at))
            rows = (await session.execute(statement)).scalars().all()

        return [row.to_domain() for row in rows]

    @override
    async def orders_of(self, run_id: RunId) -> list[Order]:
        async with self._db.owner_session() as session:
            statement = select(OrderDTO).where(col(OrderDTO.run_id) == run_id).order_by(col(OrderDTO.created_at))
            rows = (await session.execute(statement)).scalars().all()

        return [Order(**row.model_dump()) for row in rows]

    @override
    async def follows_of(self, run_id: RunId) -> list[tuple[TradeSignal, Order]]:
        followed = select(TradeSignalDTO.decision_id).where(col(TradeSignalDTO.run_id) == run_id)
        statement = (
            select(TradeSignalDTO, OrderDTO)
            .join(OrderDTO, col(OrderDTO.decision_id) == col(TradeSignalDTO.decision_id))
            .where(col(TradeSignalDTO.followed_decision_id).in_(followed))
            .order_by(col(OrderDTO.created_at))
        )

        async with self._db.owner_session() as session:
            rows = (await session.execute(statement)).all()

        return [(signal.to_domain(), Order(**order.model_dump())) for signal, order in rows]

    @override
    async def trades(
        self, broker: ExecutionProvider, since: datetime | None, limit: int, offset: int
    ) -> list[tuple[Order, SystemStats]]:
        statement = (
            select(OrderDTO, WorkflowRunDTO)
            .join(WorkflowRunDTO, col(WorkflowRunDTO.run_id) == col(OrderDTO.run_id))
            .where(col(OrderDTO.filled_quantity) > 0, col(WorkflowRunDTO.execution_provider) == broker)
            .order_by(col(OrderDTO.created_at).desc())
        )

        if since is not None:
            statement = statement.where(col(OrderDTO.created_at) >= since)

        async with self._db.owner_session() as session:
            rows = (await session.execute(statement.offset(offset).limit(limit))).all()
            pairs = [(Order(**order.model_dump()), SystemStats(**run.model_dump())) for order, run in rows]
            followed_ids = [run.followed_run_id for _, run in pairs if run.followed_run_id is not None]
            followed_rows = await session.execute(select(WorkflowRunDTO).where(col(WorkflowRunDTO.run_id).in_(followed_ids)))
            followed = {row.run_id: SystemStats(**row.model_dump()) for row in followed_rows.scalars()}

        return [(order, followed.get(run.followed_run_id, run) if run.followed_run_id else run) for order, run in pairs]

    @override
    async def runs_of(self, workflow: Workflow, broker: ExecutionProvider, since: datetime | None) -> list[SystemStats]:
        statement = (
            select(WorkflowRunDTO)
            .where(col(WorkflowRunDTO.workflow) == workflow, col(WorkflowRunDTO.execution_provider) == broker)
            .order_by(col(WorkflowRunDTO.start_time))
        )

        if since is not None:
            statement = statement.where(col(WorkflowRunDTO.start_time) >= since)

        async with self._db.owner_session() as session:
            rows = (await session.execute(statement)).scalars().all()

        return [SystemStats(**row.model_dump()) for row in rows]

    @override
    async def first_fill(self, workflow: Workflow, broker: ExecutionProvider, since: datetime | None) -> datetime | None:
        statement = (
            select(OrderDTO.created_at)
            .join(WorkflowRunDTO, col(WorkflowRunDTO.run_id) == col(OrderDTO.run_id))
            .where(
                col(OrderDTO.filled_quantity) > 0,
                col(WorkflowRunDTO.workflow) == workflow,
                col(WorkflowRunDTO.execution_provider) == broker,
            )
            .order_by(col(OrderDTO.created_at))
            .limit(1)
        )

        if since is not None:
            statement = statement.where(col(OrderDTO.created_at) >= since)

        async with self._db.owner_session() as session:
            return (await session.execute(statement)).scalar_one_or_none()

    @override
    async def buy_orders(self, broker: ExecutionProvider, since: datetime) -> list[Order]:
        statement = (
            select(OrderDTO)
            .join(WorkflowRunDTO, col(WorkflowRunDTO.run_id) == col(OrderDTO.run_id))
            .where(
                col(WorkflowRunDTO.execution_provider) == broker,
                col(OrderDTO.action) == TradeAction.BUY,
                col(OrderDTO.created_at) >= since,
            )
            .order_by(col(OrderDTO.created_at))
        )

        async with self._db.owner_session() as session:
            rows = (await session.execute(statement)).scalars().all()

        return [Order(**row.model_dump()) for row in rows]
