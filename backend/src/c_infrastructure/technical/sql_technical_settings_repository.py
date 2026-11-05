from dataclasses import replace
from typing import override

from sqlalchemy import delete, insert, update
from sqlalchemy.exc import IntegrityError
from sqlmodel import col, select

from a_domain.ports.analysis.technical_settings_repository import ITechnicalSettingsRepository
from a_domain.rules.technical.strategy import TechnicalSettings
from a_domain.types.errors import TechnicalSettingsConflictError
from c_infrastructure.database.db_connector import DatabaseConnector
from c_infrastructure.database.models.technical_settings_dto import (
    TechnicalFormulaNodeDTO,
    TechnicalIndicatorDTO,
    TechnicalRuleDTO,
    TechnicalSettingsDTO,
    TechnicalStrategyDTO,
)

CHILD_TABLES = (TechnicalFormulaNodeDTO, TechnicalRuleDTO, TechnicalIndicatorDTO, TechnicalStrategyDTO)
"""The tables below technical_settings, children first: the order a save deletes an owner's rows in."""


class SqlTechnicalSettingsRepository(ITechnicalSettingsRepository):
    """
    One owner's technical settings in ordinary SQL tables, on SQLite or PostgreSQL, through a connector bound to that
    owner. A save replaces the owner's rows in the same transaction that checks and raises the revision.
    """

    def __init__(self, db: DatabaseConnector) -> None:
        self._db = db

    @override
    async def load(self, initial: TechnicalSettings) -> TechnicalSettings:
        owner_id = self._db.owner_id

        async with self._db.owner_session() as session:
            if await session.get(TechnicalSettingsDTO, owner_id) is None:
                session.add(TechnicalSettingsDTO.from_domain(owner_id, replace(initial, revision=0)))

                try:
                    await session.flush()
                    for table, rows in TechnicalSettingsDTO.child_rows(owner_id, initial):
                        await session.execute(insert(table), rows)
                    await session.commit()
                except IntegrityError:
                    await session.rollback()
                    if await session.get(TechnicalSettingsDTO, owner_id) is None:
                        raise

            settings = await session.get(TechnicalSettingsDTO, owner_id, populate_existing=True)
            revision = settings.revision if settings else None
            rows = {table: (await session.execute(select(table))).scalars().all() for table in CHILD_TABLES}
            again = await session.get(TechnicalSettingsDTO, owner_id, populate_existing=True)

        if settings is None or again is None or again.revision != revision:
            raise TechnicalSettingsConflictError(f"The technical settings of {owner_id} changed while being read. Read them again.")

        return settings.to_domain(rows)

    @override
    async def save(self, settings: TechnicalSettings) -> TechnicalSettings:
        saved = replace(settings, revision=settings.revision + 1)
        claim = (
            update(TechnicalSettingsDTO)
            .where(col(TechnicalSettingsDTO.revision) == settings.revision)
            .values(active_strategy_id=saved.active_strategy_id, buzz_strategy_id=saved.buzz_strategy_id, revision=saved.revision)
            .returning(col(TechnicalSettingsDTO.revision))
        )

        async with self._db.owner_session() as session:
            if (await session.execute(claim)).scalar_one_or_none() is None:
                raise TechnicalSettingsConflictError(
                    "The technical settings changed after they were read. Read them again before saving."
                )

            for table in CHILD_TABLES:
                await session.execute(delete(table))

            for table, rows in TechnicalSettingsDTO.child_rows(self._db.owner_id, saved):
                await session.execute(insert(table), rows)

            await session.commit()

        return saved
