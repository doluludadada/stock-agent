from datetime import UTC, date, datetime, timedelta

import pytest

from a_domain.types.enums import TradingPhase
from c_infrastructure.system.market_clock import TAIWAN_TIMEZONE, TaiwanMarketClock


class ClockAt(TaiwanMarketClock):
    def __init__(self, moment: datetime) -> None:
        self._moment = moment

    def now(self) -> datetime:
        return self._moment


@pytest.mark.parametrize(
    ("moment", "phase"),
    [
        (datetime(2026, 10, 19, 8, 29, tzinfo=TAIWAN_TIMEZONE), TradingPhase.CLOSED),
        (datetime(2026, 10, 19, 8, 30, tzinfo=TAIWAN_TIMEZONE), TradingPhase.OPENING_AUCTION),
        (datetime(2026, 10, 19, 8, 59, 59, tzinfo=TAIWAN_TIMEZONE), TradingPhase.OPENING_AUCTION),
        (datetime(2026, 10, 19, 9, 0, tzinfo=TAIWAN_TIMEZONE), TradingPhase.CONTINUOUS),
        (datetime(2026, 10, 19, 13, 24, 59, tzinfo=TAIWAN_TIMEZONE), TradingPhase.CONTINUOUS),
        (datetime(2026, 10, 19, 13, 25, tzinfo=TAIWAN_TIMEZONE), TradingPhase.CLOSING_AUCTION),
        (datetime(2026, 10, 19, 13, 29, 59, tzinfo=TAIWAN_TIMEZONE), TradingPhase.CLOSING_AUCTION),
        (datetime(2026, 10, 19, 13, 30, tzinfo=TAIWAN_TIMEZONE), TradingPhase.CLOSED),
        (datetime(2026, 10, 24, 10, 0, tzinfo=TAIWAN_TIMEZONE), TradingPhase.CLOSED),
    ],
)
def test_a_weekday_runs_the_opening_auction_continuous_trading_and_the_closing_auction(moment: datetime, phase: TradingPhase) -> None:
    assert ClockAt(moment).trading_phase() == phase


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


@pytest.mark.parametrize(
    ("moment", "settled_session"),
    [
        (datetime(2026, 10, 30, 14, 59), date(2026, 10, 29)),
        (datetime(2026, 10, 30, 15, 0), date(2026, 10, 30)),
        (datetime(2026, 10, 31, 2, 10), date(2026, 10, 30)),
        (datetime(2026, 11, 2, 9, 0), date(2026, 10, 30)),
        (datetime(2026, 11, 2, 15, 30), date(2026, 11, 2)),
    ],
    ids=["fri-14:59-is-thu", "fri-15:00-is-fri", "sat-is-fri", "mon-09:00-is-previous-fri", "mon-15:30-is-mon"],
)
def test_the_last_settled_session_is_the_latest_weekday_settled_by_three_pm(moment: datetime, settled_session: date) -> None:
    assert ClockAt(moment.replace(tzinfo=TAIWAN_TIMEZONE)).last_settled_session() == settled_session


@pytest.mark.parametrize(
    ("moment", "sessions", "close"),
    [
        (datetime(2026, 10, 30, 18, 0), 1, datetime(2026, 11, 2, 13, 30)),
        (datetime(2026, 10, 31, 9, 0), 1, datetime(2026, 11, 2, 13, 30)),
        (datetime(2026, 11, 2, 8, 45), 1, datetime(2026, 11, 2, 13, 30)),
        (datetime(2026, 11, 2, 9, 0), 1, datetime(2026, 11, 3, 13, 30)),
        (datetime(2026, 11, 2, 15, 0), 1, datetime(2026, 11, 3, 13, 30)),
        (datetime(2026, 10, 29, 18, 0), 2, datetime(2026, 11, 2, 13, 30)),
        (datetime(2026, 10, 30, 18, 0), 5, datetime(2026, 11, 6, 13, 30)),
    ],
    ids=["fri-evening-1", "sat-1", "mon-pre-open-1", "mon-open-1", "mon-after-close-1", "thu-evening-2", "fri-evening-5"],
)
def test_a_session_count_ends_at_the_close_of_that_many_weekday_sessions_opening_after_the_moment(
    moment: datetime, sessions: int, close: datetime
) -> None:
    clock = TaiwanMarketClock()

    assert clock.session_close_after(moment.replace(tzinfo=TAIWAN_TIMEZONE), sessions) == close.replace(tzinfo=TAIWAN_TIMEZONE)
