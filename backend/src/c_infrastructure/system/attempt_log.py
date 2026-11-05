from collections.abc import Mapping
from datetime import datetime, timedelta
from typing import override

from a_domain.ports.system.attempt_log import AttemptKey, IAttemptLog
from a_domain.rules.system.attempt_limit import AttemptLimitRule


class MemoryAttemptLog(IAttemptLog):
    """
    The attempts in this process's memory: per key, when each was made and when it leaves its window. A write forgets
    the written key's attempts past their window, and every key's once the log holds twice the keys its last sweep
    kept, so keys never asked again cannot pile up and a write costs the same on average however many keys there are.
    Nothing here awaits, so a record cannot interleave with another.
    """

    def __init__(self) -> None:
        self._attempts: dict[AttemptKey, list[tuple[datetime, datetime]]] = {}
        self._swept_keys = 1

    @override
    async def record(self, key: AttemptKey, at: datetime, window: timedelta) -> list[datetime]:
        if len(self._attempts) >= 2 * self._swept_keys:
            self._attempts = {
                kept_key: kept
                for kept_key, attempts in self._attempts.items()
                if (kept := [attempt for attempt in attempts if attempt[1] > at])
            }
            self._swept_keys = max(len(self._attempts), 1)

        earlier = [attempt for attempt in self._attempts.get(key, []) if attempt[1] > at]
        self._attempts[key] = [*earlier, (at, at + window)]

        return [made for made, _ in earlier]

    @override
    async def admit(self, at: datetime, limits: Mapping[AttemptKey, AttemptLimitRule]) -> datetime | None:
        earlier = {key: await self.record(key, at, limit.window) for key, limit in limits.items()}
        retries = [retry_at for key, limit in limits.items() if (retry_at := limit.apply(earlier[key], at)) is not None]

        if not retries:
            return None

        for key in limits:
            await self.forget(key, at)

        return max(retries)

    @override
    async def forget(self, key: AttemptKey, at: datetime) -> None:
        attempts = self._attempts.get(key, [])
        made = [attempt[0] for attempt in attempts]

        if at in made:
            del attempts[made.index(at)]

    @override
    async def clear(self, key: AttemptKey) -> None:
        self._attempts.pop(key, None)
