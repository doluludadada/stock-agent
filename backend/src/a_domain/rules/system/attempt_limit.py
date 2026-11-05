from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Annotated

from pydantic import Field
from pydantic.dataclasses import dataclass


@dataclass(frozen=True)
class AttemptLimitRule:
    """
    Refuses an attempt once `max_attempts` were made within `window` before it. One instance per limit: sign-in
    failures per sign-in name and client, sign-in failures per client, registrations per client.
    """

    max_attempts: Annotated[int, Field(gt=0)]
    window: timedelta

    def apply(self, earlier: Sequence[datetime], now: datetime) -> datetime | None:
        """
        When the attempt made `now` may be tried: None for now, or the moment the oldest counted attempt leaves the
        window. `earlier` are the attempts before it inside the window, which the attempt log keeps.
        """
        if len(earlier) < self.max_attempts:
            return None

        return sorted(earlier)[-self.max_attempts] + self.window
