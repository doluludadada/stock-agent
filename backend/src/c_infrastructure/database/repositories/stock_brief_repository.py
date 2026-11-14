from datetime import date, datetime
from typing import override

from sqlalchemy import and_, delete, func, inspect, literal, or_, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlmodel import col, select

from a_domain.model.analysis.stock_brief import StockBrief
from a_domain.ports.ai.stock_brief_repository import IStockBriefRepository
from a_domain.types.enums import BriefStatus
from c_infrastructure.database.db_connector import DatabaseConnector
from c_infrastructure.database.models.stock_brief_dto import StockBriefDTO


class SqlStockBriefRepository(IStockBriefRepository):
    """
    The stock_briefs table, shared by every user. A claim is one transaction: an UPDATE that takes over a failed or an
    abandoned brief of the day, else an INSERT ... SELECT ... WHERE the day's stocks are under the limit ... ON CONFLICT
    DO NOTHING, so the primary key lets one of the calls made together take a stock's day. The table is locked
    against other claims until the commit, so the day's count is exact.
    """

    def __init__(self, db: DatabaseConnector) -> None:
        self._db = db

    @override
    async def find(self, stock_id: str, day: date) -> StockBrief | None:
        async with self._db.get_session() as session:
            row = await session.get(StockBriefDTO, (stock_id, day))

        return row.to_domain() if row is not None else None

    @override
    async def latest_written(self, stock_id: str, before: date) -> StockBrief | None:
        written = (
            select(StockBriefDTO)
            .where(col(StockBriefDTO.stock_id) == stock_id, col(StockBriefDTO.day) < before)
            .where(col(StockBriefDTO.status) == BriefStatus.WRITTEN.value)
            .order_by(col(StockBriefDTO.day).desc())
            .limit(1)
        )

        async with self._db.get_session() as session:
            row = (await session.execute(written)).scalar_one_or_none()

        return row.to_domain() if row is not None else None

    @override
    async def claimed_stocks(self, day: date) -> int:
        async with self._db.get_session() as session:
            return (await session.execute(select(func.count()).where(col(StockBriefDTO.day) == day))).scalar_one()

    @override
    async def claim(self, brief: StockBrief, daily_stocks: int, stale_before: datetime) -> bool:
        values = StockBriefDTO.values_of(brief)
        this = and_(col(StockBriefDTO.stock_id) == brief.stock_id, col(StockBriefDTO.day) == brief.day)
        abandoned = and_(col(StockBriefDTO.status) == BriefStatus.WRITING.value, col(StockBriefDTO.claimed_at) < stale_before)
        retakable = or_(col(StockBriefDTO.status) == BriefStatus.FAILED.value, abandoned)
        retake = update(StockBriefDTO).where(this, retakable).values(values).returning(col(StockBriefDTO.stock_id))
        claimed_today = select(func.count()).where(col(StockBriefDTO.day) == brief.day).scalar_subquery()
        columns = inspect(StockBriefDTO).columns
        row = select(*(literal(value, columns[name].type).label(name) for name, value in values.items())).where(
            claimed_today < daily_stocks
        )

        async with self._db.get_session() as session:
            await session.execute(text(f"LOCK TABLE {StockBriefDTO.__tablename__} IN SHARE ROW EXCLUSIVE MODE"))

            taken = (await session.execute(retake)).scalar_one_or_none()

            if taken is None:
                first = insert(StockBriefDTO).from_select(list(values), row).on_conflict_do_nothing()
                taken = (await session.execute(first.returning(col(StockBriefDTO.stock_id)))).scalar_one_or_none()

            await session.commit()

        return taken is not None

    @override
    async def save(self, brief: StockBrief) -> None:
        async with self._db.get_session() as session:
            await session.merge(StockBriefDTO.from_domain(brief))
            await session.commit()

    @override
    async def release(self, stock_id: str, day: date) -> None:
        async with self._db.get_session() as session:
            await session.execute(delete(StockBriefDTO).where(col(StockBriefDTO.stock_id) == stock_id, col(StockBriefDTO.day) == day))
            await session.commit()
