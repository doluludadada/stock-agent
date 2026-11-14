import asyncio
import time
from dataclasses import dataclass, field
from datetime import timedelta
from enum import StrEnum, auto

from sqlalchemy import Interval, func, literal
from sqlalchemy.dialects.postgresql import insert
from sqlmodel import col

from c_infrastructure.database.db_connector import DatabaseConnector
from c_infrastructure.database.models.request_pace_dto import RequestPaceDTO


@dataclass(eq=False)
class RequestPace:
    """
    When the latest request to one host left, kept by whoever shares that host's limit in one process. A request waits
    its turn, then until the interval has passed since the request before it, so requests made at once leave one
    interval apart.
    """

    last_request_at: float | None = None
    turn: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def wait(self, interval_seconds: float) -> None:
        async with self.turn:
            if self.last_request_at is not None:
                await asyncio.sleep(max(0.0, interval_seconds - (time.monotonic() - self.last_request_at)))

            self.last_request_at = time.monotonic()


class PacedHost(StrEnum):
    """A host whose pace every process on the database shares, by its row in request_paces."""

    MOPS = auto()
    """Every request to MOPS: the income statements, the revenue summaries and a company's basic information."""

    DOCUMENT_SITE = auto()
    """The exchange's document site, which the annual reports are read from."""


@dataclass(eq=False)
class SharedRequestPace:
    """
    One host's pace kept in the database, so every process that reads the host shares it: the Web API's timer, a
    viewer's request and an operator's command made at once leave one interval apart, where a pace each process kept
    for itself would let one of each leave together. A request reserves when it may leave in one statement, the later
    of now and one interval after the time reserved before it, by the database's clock, and sleeps until then, so no
    lock is held while it waits.
    """

    db: DatabaseConnector
    host: PacedHost

    async def wait(self, interval_seconds: float) -> None:
        next_at, now = col(RequestPaceDTO.next_at), func.timezone("UTC", func.now())
        interval = literal(timedelta(seconds=interval_seconds), Interval())
        reserve = (
            insert(RequestPaceDTO)
            .values(host=self.host.value, next_at=now)
            .on_conflict_do_update(index_elements=["host"], set_={"next_at": func.greatest(next_at + interval, now)})
            .returning(func.extract("epoch", next_at - now))
        )

        async with self.db.get_session() as session:
            delay = (await session.execute(reserve)).scalar_one()
            await session.commit()

        await asyncio.sleep(max(0.0, float(delay)))


type HostPace = RequestPace | SharedRequestPace
"""The pace an adapter waits on before a request: its process's own, or the one every process shares."""
