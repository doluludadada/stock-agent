from datetime import UTC, date, datetime, timedelta

import pytest

from c_infrastructure.system.market_clock import TAIWAN_TIMEZONE, TaiwanMarketClock


class ClockAt(TaiwanMarketClock):
    def __init__(self, moment: datetime) -> None:
        self._moment = moment

    def now(self) -> datetime:
        return self._moment


@pytest.mark.parametrize(
    ("moment", "is_open"),
    [
        (datetime(2026, 10, 19, 8, 59, tzinfo=TAIWAN_TIMEZONE), False),
        (datetime(2026, 10, 19, 9, 0, tzinfo=TAIWAN_TIMEZONE), True),
        (datetime(2026, 10, 19, 13, 30, tzinfo=TAIWAN_TIMEZONE), True),
        (datetime(2026, 10, 19, 13, 31, tzinfo=TAIWAN_TIMEZONE), False),
        (datetime(2026, 10, 24, 10, 0, tzinfo=TAIWAN_TIMEZONE), False),
    ],
)
def test_taiwan_session_is_weekdays_from_nine_to_half_past_one(moment: datetime, is_open: bool) -> None:
    assert ClockAt(moment).is_market_open() is is_open


def test_trading_date_is_the_taipei_calendar_date() -> None:
    clock = TaiwanMarketClock()

    assert clock.to_trading_date(datetime(2026, 10, 19, 17, 0, tzinfo=UTC)) == date(2026, 10, 20)
    assert clock.now().utcoffset() == timedelta(hours=8)


@pytest.mark.parametrize(
    ("moment", "last_session"),
    [
        (datetime(2026, 10, 30, 13, 29), date(2026, 10, 29)),
        (datetime(2026, 10, 30, 13, 30), date(2026, 10, 30)),
        (datetime(2026, 10, 19, 14, 0), date(2026, 10, 19)),
        (datetime(2026, 10, 24, 10, 0), date(2026, 10, 23)),
        (datetime(2026, 10, 31, 20, 0), date(2026, 10, 30)),
        (datetime(2026, 11, 1, 8, 0), date(2026, 10, 30)),
        (datetime(2026, 11, 2, 9, 0), date(2026, 10, 30)),
        (datetime(2026, 10, 19, 10, 0), date(2026, 10, 16)),
    ],
    ids=[
        "fri-13:29-is-thu",
        "fri-13:30-is-fri",
        "mon-14:00-is-mon",
        "sat-10:00-is-fri",
        "sat-20:00-is-fri",
        "sun-is-fri",
        "mon-09:00-is-previous-fri",
        "mon-10:00-is-previous-fri",
    ],
)
def test_the_last_closed_session_is_the_latest_weekday_whose_close_has_passed(moment: datetime, last_session: date) -> None:
    assert ClockAt(moment.replace(tzinfo=TAIWAN_TIMEZONE)).last_closed_session() == last_session
