from sqlmodel import col, select

from a_domain.model.system.stats import SystemStats
from a_domain.model.trading.account_snapshot import AccountSnapshot
from a_domain.model.trading.order import Order
from a_domain.model.trading.signal import TradeSignal
from a_domain.ports.trading.trading_journal import ITradingJournal
from a_domain.types.ids import RunId
from c_infrastructure.database.db_connector import DatabaseConnector
from c_infrastructure.database.models.trading_journal_dto import AccountSnapshotDTO, OrderDTO, TradeSignalDTO, WorkflowRunDTO


class TradingJournal(ITradingJournal):
    """SQL tables workflow_runs, trade_signals, orders and account_snapshots. Every save is an upsert by primary key."""

    def __init__(self, db: DatabaseConnector) -> None:
        self._db = db

    async def save_run(self, run: SystemStats) -> None:
        async with self._db.get_session() as session:
            await session.merge(WorkflowRunDTO.model_validate(run.model_dump()))
            await session.commit()

    async def save_signals(self, run_id: RunId, signals: list[TradeSignal]) -> None:
        async with self._db.get_session() as session:
            for signal in signals:
                reports = signal.model_dump(mode="json", include={"technical_report", "ai_report"})
                await session.merge(TradeSignalDTO.model_validate({**signal.model_dump(), **reports, "run_id": run_id}))

            await session.commit()

    async def save_order(self, order: Order) -> None:
        async with self._db.get_session() as session:
            await session.merge(OrderDTO.model_validate(order.model_dump()))
            await session.commit()

    async def save_snapshot(self, snapshot: AccountSnapshot) -> None:
        async with self._db.get_session() as session:
            await session.merge(
                AccountSnapshotDTO.model_validate(snapshot.model_dump(mode="json") | snapshot.model_dump(exclude={"positions"}))
            )
            await session.commit()

    async def snapshots(self) -> list[AccountSnapshot]:
        async with self._db.get_session() as session:
            result = await session.execute(select(AccountSnapshotDTO).order_by(col(AccountSnapshotDTO.taken_at)))
            rows = result.scalars().all()

        return [AccountSnapshot.model_validate(row.model_dump()) for row in rows]

    async def recent_runs(self, limit: int) -> list[SystemStats]:
        async with self._db.get_session() as session:
            result = await session.execute(select(WorkflowRunDTO).order_by(col(WorkflowRunDTO.start_time).desc()).limit(limit))
            rows = result.scalars().all()

        return [SystemStats.model_validate(row.model_dump()) for row in rows]

    async def find_run(self, run_id: RunId) -> SystemStats | None:
        async with self._db.get_session() as session:
            row = await session.get(WorkflowRunDTO, run_id)

        return SystemStats.model_validate(row.model_dump()) if row is not None else None

    async def signals_of(self, run_id: RunId) -> list[TradeSignal]:
        async with self._db.get_session() as session:
            statement = select(TradeSignalDTO).where(col(TradeSignalDTO.run_id) == run_id).order_by(col(TradeSignalDTO.generated_at))
            rows = (await session.execute(statement)).scalars().all()

        return [TradeSignal.model_validate(row.model_dump(exclude={"run_id"})) for row in rows]

    async def orders_of(self, run_id: RunId) -> list[Order]:
        async with self._db.get_session() as session:
            statement = select(OrderDTO).where(col(OrderDTO.run_id) == run_id).order_by(col(OrderDTO.created_at))
            rows = (await session.execute(statement)).scalars().all()

        return [Order.model_validate(row.model_dump()) for row in rows]
