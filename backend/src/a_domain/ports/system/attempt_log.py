from collections.abc import Mapping
from datetime import datetime, timedelta
from typing import Protocol

from pydantic.dataclasses import dataclass

from a_domain.rules.system.attempt_limit import AttemptLimitRule
from a_domain.types.enums import AttemptLimit
from a_domain.types.values import SignInName


@dataclass(frozen=True)
class AttemptKey:
    """What one limit counts an attempt under: the client address, and for SIGN_IN_NAME the sign-in name too."""

    limit: AttemptLimit
    client: str
    name: SignInName = ""


class IAttemptLog(Protocol):
    """
    Recent sign-in and registration attempts by key. Kept by this process only: the Web API runs one worker, and a
    restart forgets them. An attempt is recorded before it is tried, so attempts that run at once each count the ones
    before them, and the attempt the limit refuses, or the sign-in that succeeds, is taken back.
    """

    async def record(self, key: AttemptKey, at: datetime, window: timedelta) -> list[datetime]:
        """
        Records an attempt made at `at`, which counts for `window`, and returns when the key's earlier attempts still
        inside their window were made. Attempts past their window are forgotten on the way, every key's in time.
        """
        ...

    async def admit(self, at: datetime, limits: Mapping[AttemptKey, AttemptLimitRule]) -> datetime | None:
        """
        One attempt made at `at`, counted under every key by its limit: None when every limit lets it be tried. When
        one refuses, the attempt is taken back from every key, and the answer is when the last of them allows the next.
        """
        ...

    async def forget(self, key: AttemptKey, at: datetime) -> None:
        """Takes back one attempt the key recorded at `at`. Taking back one never recorded changes nothing."""
        ...

    async def clear(self, key: AttemptKey) -> None: ...
