# backend/src/c_infrastructure/system/market_clock.py

from datetime import date, datetime, time, timedelta
from typing import override
from zoneinfo import ZoneInfo

from a_domain.ports.system.market_clock import IMarketClock
from a_domain.types.enums import TradingPhase

TAIWAN_TIMEZONE = ZoneInfo("Asia/Taipei")
TAIWAN_SESSION_OPEN = time(9, 0)
TAIWAN_SESSION_CLOSE = time(13, 30)
# A session's daily bar is final from 15:00: the after-hours fixed-price session ends at 14:30, and delayed feeds
# such as Yahoo's run 20 minutes behind.
TAIWAN_SESSION_SETTLED = time(15, 0)

TAIWAN_TRADING_DAY: tuple[tuple[time, TradingPhase], ...] = (
    (TAIWAN_SESSION_CLOSE, TradingPhase.CLOSED),
    (time(13, 25), TradingPhase.CLOSING_AUCTION),
    (TAIWAN_SESSION_OPEN, TradingPhase.CONTINUOUS),
    (time(8, 30), TradingPhase.OPENING_AUCTION),
)
"""The phase that starts at each time of a weekday, latest first; before 08:30 the market is CLOSED."""


class TaiwanMarketClock(IMarketClock):
    """
    Asia/Taipei wall clock and the regular TWSE/TPEX trading day on weekdays (TAIWAN_TRADING_DAY).

    TWSE and TPEx both take orders from 08:30, match the opening call auction at 09:00, trade continuously
    09:00-13:25, and run the closing call auction 13:25-13:30, which takes limit ROD orders only. Sources, read
    2026-10-31: the TWSE trading mechanism page (https://www.twse.com.tw/en/products/system/trading.html) and the
    TPEx trading system overview, sections 5 and 6 (https://www.tpex.org.tw/zh-tw/mainboard/trading/rules/system.html).
    """

    @override
    def now(self) -> datetime:
        return datetime.now(TAIWAN_TIMEZONE)

    @override
    def today(self) -> date:
        return self.now().date()

    @override
    def to_market_datetime(self, value: datetime) -> datetime:
        return value.astimezone(TAIWAN_TIMEZONE)

    @override
    def to_trading_date(self, value: datetime) -> date:
        return self.to_market_datetime(value).date()

    @override
    def history_window(self, lookback_days: int) -> tuple[datetime, datetime]:
        end_day = self.today()
        start_day = end_day - timedelta(days=lookback_days)

        return (
            datetime.combine(start_day, time.min, tzinfo=TAIWAN_TIMEZONE),
            datetime.combine(end_day, time.max, tzinfo=TAIWAN_TIMEZONE),
        )

    @override
    def session_close_after(self, value: datetime, sessions: int) -> datetime:
        moment = self.to_market_datetime(value)
        day = moment.date() if moment.time() < TAIWAN_SESSION_OPEN else moment.date() + timedelta(days=1)
        opened = 0

        while True:
            if day.weekday() < 5:
                opened += 1

                if opened >= sessions:
                    return datetime.combine(day, TAIWAN_SESSION_CLOSE, tzinfo=TAIWAN_TIMEZONE)

            day += timedelta(days=1)

    @override
    def last_closed_session(self) -> date:
        now = self.now()
        day = now.date() if now.time() >= TAIWAN_SESSION_CLOSE else now.date() - timedelta(days=1)

        while day.weekday() >= 5:
            day -= timedelta(days=1)

        return day

    @override
    def last_settled_session(self) -> date:
        now = self.now()
        day = now.date() if now.time() >= TAIWAN_SESSION_SETTLED else now.date() - timedelta(days=1)

        while day.weekday() >= 5:
            day -= timedelta(days=1)

        return day

    @override
    def trading_phase(self) -> TradingPhase:
        now = self.now()

        if now.weekday() >= 5:
            return TradingPhase.CLOSED

        return next((phase for start, phase in TAIWAN_TRADING_DAY if now.time() >= start), TradingPhase.CLOSED)
