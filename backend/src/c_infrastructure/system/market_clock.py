# backend/src/c_infrastructure/system/market_clock.py

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from a_domain.ports.system.market_clock import IMarketClock

TAIWAN_TIMEZONE = ZoneInfo("Asia/Taipei")
TAIWAN_SESSION_OPEN = time(9, 0)
TAIWAN_SESSION_CLOSE = time(13, 30)


class TaiwanMarketClock(IMarketClock):
    """Asia/Taipei wall clock and the regular TWSE/TPEX trading session (Mon-Fri 09:00-13:30)."""

    def now(self) -> datetime:
        return datetime.now(TAIWAN_TIMEZONE)

    def today(self) -> date:
        return self.now().date()

    def to_market_datetime(self, value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=TAIWAN_TIMEZONE)

        return value.astimezone(TAIWAN_TIMEZONE)

    def to_trading_date(self, value: datetime) -> date:
        return self.to_market_datetime(value).date()

    def history_window(self, lookback_days: int) -> tuple[datetime, datetime]:
        end_day = self.today()
        start_day = end_day - timedelta(days=lookback_days)

        return (
            datetime.combine(start_day, time.min, tzinfo=TAIWAN_TIMEZONE),
            datetime.combine(end_day, time.max, tzinfo=TAIWAN_TIMEZONE),
        )

    def last_closed_session(self) -> date:
        now = self.now()
        day = now.date() if now.time() >= TAIWAN_SESSION_CLOSE else now.date() - timedelta(days=1)

        while day.weekday() >= 5:
            day -= timedelta(days=1)

        return day

    def is_market_open(self) -> bool:
        now = self.now()

        return now.weekday() < 5 and TAIWAN_SESSION_OPEN <= now.time() <= TAIWAN_SESSION_CLOSE
