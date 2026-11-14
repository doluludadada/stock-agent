from datetime import date
from typing import Protocol

from pydantic.dataclasses import dataclass

from a_domain.types.values import NonEmptyText


@dataclass(frozen=True, kw_only=True)
class SystemWriting:
    """One round of the site's own writing: the stocks it writes for once a session's daily data is held."""

    session: date
    """The latest session the site held daily bars of when the round began. One round exists per session."""

    started_on: date
    """The Taipei calendar day the round began: a stock is done once it has a written brief of that day or a later one."""

    stock_ids: list[NonEmptyText]
    """The stocks of the round, in the order they are written for."""


class ISystemWritingLog(Protocol):
    """
    The rounds of the site's own writing, kept across restarts, so the stocks of a session's round are chosen once and
    a later look at the round reads them here instead of ranking the market again.
    """

    async def find(self, session: date) -> SystemWriting | None:
        """The round of that session, or None while none began."""
        ...

    async def begin(self, writing: SystemWriting) -> SystemWriting:
        """Keeps `writing` as its session's round unless one began already, and answers the session's round as kept."""
        ...
