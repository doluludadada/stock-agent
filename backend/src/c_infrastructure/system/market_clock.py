# backend/src/c_infrastructure/system/market_clock.py

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from a_domain.ports.system.market_clock import IMarketClock
from a_domain.types.enums import TradingPhase

TAIWAN_TIMEZONE = ZoneInfo("Asia/Taipei")
TAIWAN_SESSION_OPEN = time(9, 0)
TAIWAN_SESSION_CLOSE = time(13, 30)

TAIWAN_TRADING_DAY: tuple[tuple[time, TradingPhase], ...] = (
    (TAIWAN_SESSION_CLOSE, TradingPhase.CLOSED),
    (time(13, 25), TradingPhase.CLOSING_AUCTION),
    (TAIWAN_SESSION_OPEN, TradingPhase.CONTINUOUS),
    (time(8, 30), TradingPhase.OPENING_AUCTION),
)
"""
The phase that starts at each time of a weekday, latest first; before 08:30 the market is CLOSED. TWSE and TPEx
both: orders from 08:30, the opening call auction matches at 09:00, continuous trading runs 09:00-13:25, and the
closing call auction 13:25-13:30 takes limit ROD orders only. Sources, read 2026-10-31: TWSE trading mechanism
(https://www.twse.com.tw/en/products/system/trading.html) and TPEx 上櫃有價證券交易系統簡介 五、撮合方式 and 六、委託種類
(https://www.tpex.org.tw/zh-tw/mainboard/trading/rules/system.html).
"""


class TaiwanMarketClock(IMarketClock):
    """Asia/Taipei wall clock and the regular TWSE/TPEX trading day on weekdays (TAIWAN_TRADING_DAY)."""

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

    def last_closed_session(self) -> date:
        now = self.now()
        day = now.date() if now.time() >= TAIWAN_SESSION_CLOSE else now.date() - timedelta(days=1)

        while day.weekday() >= 5:
            day -= timedelta(days=1)

        return day

    def trading_phase(self) -> TradingPhase:
        now = self.now()

        if now.weekday() >= 5:
            return TradingPhase.CLOSED

        return next((phase for start, phase in TAIWAN_TRADING_DAY if now.time() >= start), TradingPhase.CLOSED)
