from datetime import date, datetime
from typing import Any, override

from sqlalchemy import ColumnElement, ScalarSelect, and_, delete, exists, func, inspect, literal, or_, text, true, update
from sqlalchemy.dialects.postgresql import insert
from sqlmodel import col, select

from a_domain.model.analysis.stock_brief import StockBrief
from a_domain.ports.ai.stock_brief_repository import IStockBriefRepository
from a_domain.types.enums import BriefStatus
from c_infrastructure.database.db_connector import DatabaseConnector
from c_infrastructure.database.models.stock_brief_dto import BriefColumns
from c_infrastructure.database.models.system_writing_dto import SystemTextDTO


class SqlStockBriefRepository(IStockBriefRepository):
    """
    One kind of AI text in its own table (`table`: stock_briefs for the daily briefs, company_cards for the company
    cards, world_briefs for the world briefs), shared by every user. A claim is one transaction: an UPDATE that takes
    over a failed or an abandoned text of the day, else an INSERT ... SELECT ... WHERE the day's stocks are under the
    limit ... ON CONFLICT DO NOTHING, so the primary key lets one of the calls made together take a stock's day. The
    table is locked against other claims until the commit, so the day's count is exact. A text the site's own writing
    claimed is named in system_texts in the same transaction, and the day's count leaves it out; a viewer's claim that
    takes it over removes the name, so it counts from then on.
    """

    def __init__(self, db: DatabaseConnector, table: type[BriefColumns]) -> None:
        self._db = db
        self._table = table

    @override
    async def find(self, stock_id: str, day: date) -> StockBrief | None:
        async with self._db.get_session() as session:
            row = await session.get(self._table, (stock_id, day))

        return row.to_domain() if row is not None else None

    @override
    async def latest_written(self, stock_id: str, before: date) -> StockBrief | None:
        table = self._table
        written = (
            select(table)
            .where(col(table.stock_id) == stock_id, col(table.day) < before)
            .where(col(table.status) == BriefStatus.WRITTEN.value)
            .order_by(col(table.day).desc())
            .limit(1)
        )

        async with self._db.get_session() as session:
            row = (await session.execute(written)).scalar_one_or_none()

        return row.to_domain() if row is not None else None

    @override
    async def recent(self, stock_id: str, limit: int) -> list[StockBrief]:
        table = self._table
        written = (
            select(table)
            .where(col(table.stock_id) == stock_id, col(table.status) == BriefStatus.WRITTEN.value)
            .order_by(col(table.day).desc())
            .limit(limit)
        )

        async with self._db.get_session() as session:
            rows = (await session.execute(written)).scalars().all()

        return [row.to_domain() for row in rows]

    @override
    async def claimed_stocks(self, day: date) -> int:
        async with self._db.get_session() as session:
            return (await session.execute(select(viewers_stocks(self._table, day)))).scalar_one()

    @override
    async def claim(self, brief: StockBrief, daily_stocks: int | None, stale_before: datetime) -> bool:
        table = self._table
        values = table.values_of(brief)
        this = and_(col(table.stock_id) == brief.stock_id, col(table.day) == brief.day)
        abandoned = and_(col(table.status) == BriefStatus.WRITING.value, col(table.claimed_at) < stale_before)
        retakable = or_(col(table.status) == BriefStatus.FAILED.value, abandoned)
        retake = update(table).where(this, retakable).values(values).returning(col(table.stock_id))
        under_limit = true() if daily_stocks is None else viewers_stocks(table, brief.day) < daily_stocks
        columns = inspect(table).columns
        row = select(*(literal(value, columns[name].type).label(name) for name, value in values.items())).where(under_limit)

        async with self._db.get_session() as session:
            await session.execute(text(f"LOCK TABLE {table.__tablename__} IN SHARE ROW EXCLUSIVE MODE"))

            taken = (await session.execute(retake)).scalar_one_or_none()

            if taken is None:
                first = insert(table).from_select(list(values), row).on_conflict_do_nothing()
                taken = (await session.execute(first.returning(col(table.stock_id)))).scalar_one_or_none()

            if taken is not None and daily_stocks is None:
                await session.execute(insert(SystemTextDTO).on_conflict_do_nothing(), [system_text(table, brief.stock_id, brief.day)])

            if taken is not None and daily_stocks is not None:
                await session.execute(delete(SystemTextDTO).where(names_text(table, brief.stock_id, brief.day)))

            await session.commit()

        return taken is not None

    @override
    async def save(self, brief: StockBrief) -> None:
        async with self._db.get_session() as session:
            await session.merge(self._table.from_domain(brief))
            await session.commit()

    @override
    async def release(self, stock_id: str, day: date) -> None:
        table = self._table

        async with self._db.get_session() as session:
            await session.execute(delete(table).where(col(table.stock_id) == stock_id, col(table.day) == day))
            await session.execute(delete(SystemTextDTO).where(names_text(table, stock_id, day)))
            await session.commit()


def system_text(table: type[BriefColumns], stock_id: str, day: date) -> dict[str, Any]:
    """The row of system_texts that names the stock's text of that day in `table`."""
    return {"text_table": table.__tablename__, "stock_id": stock_id, "day": day}


def names_text(table: type[BriefColumns], stock_id: Any, day: Any) -> ColumnElement[bool]:
    """Whether a row of system_texts names the text of `table` for that stock and day, each a value or a column."""
    return and_(
        col(SystemTextDTO.text_table) == table.__tablename__, col(SystemTextDTO.stock_id) == stock_id, col(SystemTextDTO.day) == day
    )


def viewers_stocks(table: type[BriefColumns], day: date) -> ScalarSelect[int]:
    """How many stocks have a text of that day in `table` that the site's own writing did not claim."""
    own = exists().where(names_text(table, col(table.stock_id), col(table.day)))
    return select(func.count()).select_from(table).where(col(table.day) == day, ~own).scalar_subquery()
