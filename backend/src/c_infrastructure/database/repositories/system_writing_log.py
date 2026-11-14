import json
from datetime import date
from typing import override

from sqlalchemy.dialects.postgresql import insert

from a_domain.ports.ai.system_writing_log import ISystemWritingLog, SystemWriting
from c_infrastructure.database.db_connector import DatabaseConnector
from c_infrastructure.database.models.system_writing_dto import SystemWritingDTO


class SqlSystemWritingLog(ISystemWritingLog):
    """The system_writings table. A round begins with INSERT ... ON CONFLICT DO NOTHING, so of two begun at once one is kept."""

    def __init__(self, db: DatabaseConnector) -> None:
        self._db = db

    @override
    async def find(self, session: date) -> SystemWriting | None:
        async with self._db.get_session() as database:
            row = await database.get(SystemWritingDTO, session)

        return row.to_domain() if row is not None else None

    @override
    async def begin(self, writing: SystemWriting) -> SystemWriting:
        row = {"session_date": writing.session, "started_on": writing.started_on, "stock_ids": json.dumps(writing.stock_ids)}

        async with self._db.get_session() as database:
            await database.execute(insert(SystemWritingDTO).on_conflict_do_nothing(), [row])
            await database.commit()
            kept = await database.get(SystemWritingDTO, writing.session)

        return kept.to_domain() if kept is not None else writing
