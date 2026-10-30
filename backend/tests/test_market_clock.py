from datetime import date, datetime

import pytest

from c_infrastructure.system.market_clock import TAIWAN_TIMEZONE, TaiwanMarketClock


class StoppedClock(TaiwanMarketClock):
    def __init__(self, now: datetime) -> None:
        super().__init__()
        self._now = now

    def now(self) -> datetime:
        return self._now


@pytest.mark.parametrize(
    ("now", "session"),
    [
        (datetime(2026, 10, 30, 13, 29), date(2026, 10, 29)),
        (datetime(2026, 10, 30, 13, 30), date(2026, 10, 30)),
        (datetime(2026, 10, 31, 20, 0), date(2026, 10, 30)),
        (datetime(2026, 11, 1, 8, 0), date(2026, 10, 30)),
        (datetime(2026, 11, 2, 9, 0), date(2026, 10, 30)),
    ],
    ids=["fri-13:29-is-thu", "fri-13:30-is-fri", "sat-is-fri", "sun-is-fri", "mon-09:00-is-previous-fri"],
)
def test_last_closed_session(now: datetime, session: date) -> None:
    assert StoppedClock(now.replace(tzinfo=TAIWAN_TIMEZONE)).last_closed_session() == session
