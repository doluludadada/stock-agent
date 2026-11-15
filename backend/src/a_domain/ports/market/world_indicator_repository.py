from collections.abc import Sequence
from typing import Protocol

from a_domain.model.market.world_indicator import IndicatorReading


class IWorldIndicatorRepository(Protocol):
    """The world indicators' readings the site holds, one per indicator and day, shared by every user and kept across restarts."""

    async def save(self, readings: Sequence[IndicatorReading]) -> int:
        """Keeps each reading under its indicator and day, and says how many are new or changed: the same again change nothing."""
        ...

    async def latest(self) -> list[IndicatorReading]:
        """Each held indicator's newest reading with the reading held of the day before it, in the indicators' order."""
        ...
