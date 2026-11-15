from collections.abc import Sequence
from typing import override

from sqlalchemy import func, select
from sqlmodel import col

from a_domain.model.market.world_indicator import IndicatorReading
from a_domain.ports.market.world_indicator_repository import IWorldIndicatorRepository
from a_domain.types.enums import WorldIndicator
from c_infrastructure.database.db_connector import DatabaseConnector
from c_infrastructure.database.models.daily_close_archive_dto import replacing
from c_infrastructure.database.models.world_indicator_dto import WorldIndicatorReadingDTO


class SqlWorldIndicatorRepository(IWorldIndicatorRepository):
    """
    The world_indicator_readings table, shared by every user. A save reads what the table holds of the days given and
    writes only the readings that are new or changed, in one statement that replaces a row of the same indicator and
    day. A reading of an indicator the code no longer names is left in the table and never answered.
    """

    def __init__(self, db: DatabaseConnector) -> None:
        self._db = db

    @override
    async def save(self, readings: Sequence[IndicatorReading]) -> int:
        given = {(reading.indicator.value, reading.day): reading.value for reading in readings}
        days = {day for _, day in given}

        async with self._db.get_session() as session:
            held = (
                await session.execute(select(WorldIndicatorReadingDTO).where(col(WorldIndicatorReadingDTO.day).in_(days)))
            ).scalars()
            kept = {(row.indicator, row.day): row.value for row in held}
            changed = [
                {"indicator": indicator, "day": day, "value": value}
                for (indicator, day), value in given.items()
                if kept.get((indicator, day)) != value
            ]

            if changed:
                await session.execute(replacing(WorldIndicatorReadingDTO), changed)

            await session.commit()

        return len(changed)

    @override
    async def latest(self) -> list[IndicatorReading]:
        indicator, day = col(WorldIndicatorReadingDTO.indicator), col(WorldIndicatorReadingDTO.day)
        place = func.row_number().over(partition_by=indicator, order_by=day.desc()).label("place")
        newest = select(indicator, day, col(WorldIndicatorReadingDTO.value), place).subquery()

        async with self._db.get_session() as session:
            rows = (await session.execute(select(newest).where(newest.c.place <= 2).order_by(newest.c.place))).all()

        latest = {row.indicator: row for row in rows if row.place == 1}
        before = {row.indicator: row for row in rows if row.place == 2}
        return [
            IndicatorReading(
                indicator=indicator,
                day=latest[indicator.value].day,
                value=latest[indicator.value].value,
                previous_day=before[indicator.value].day if indicator.value in before else None,
                previous=before[indicator.value].value if indicator.value in before else None,
            )
            for indicator in WorldIndicator
            if indicator.value in latest
        ]
