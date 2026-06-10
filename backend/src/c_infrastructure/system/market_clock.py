# backend/src/c_infrastructure/services/market_clock.py

from datetime import date, datetime, time, timedelta, timezone, tzinfo

from a_domain.ports.system.market_clock import IMarketClock

# TODO Think a better way
TAIWAN_TIMEZONE = timezone(timedelta(hours=8), name="UTC+08:00")


# TODO: What the hell with this name?
class FixedOffsetMarketClock(IMarketClock):
    def __init__(self, market_timezone: tzinfo):
        self._timezone = market_timezone

    @property
    def timezone(self) -> tzinfo:
        return self._timezone

    def now(self) -> datetime:
        return datetime.now(self._timezone)

    def today(self) -> date:
        return self.now().date()

    def to_market_datetime(self, value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=self._timezone)

        return value.astimezone(self._timezone)

    def to_trading_date(self, value: datetime) -> date:
        return self.to_market_datetime(value).date()

    def history_window(self, lookback_days: int) -> tuple[datetime, datetime]:
        end_day = self.today()
        start_day = end_day - timedelta(days=lookback_days)

        return (
            datetime.combine(start_day, time.min, tzinfo=self._timezone),
            datetime.combine(end_day, time.max, tzinfo=self._timezone),
        )

    def is_market_open(self) -> bool:
        raise NotImplementedError("Market-open rules must be implemented by the market-specific clock.")


class TaiwanMarketClock(FixedOffsetMarketClock):
    def __init__(self):
        super().__init__(market_timezone=TAIWAN_TIMEZONE)

    def is_market_open(self) -> bool:
        now = self.now()

        if now.weekday() >= 5:
            return False

        return time(9, 0) <= now.time() <= time(13, 30)
