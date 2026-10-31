# backend/src/c_infrastructure/system/market_clock.py

from datetime import date, datetime, time, timedelta
from typing import override
from zoneinfo import ZoneInfo

from a_domain.ports.system.market_clock import IMarketClock
from a_domain.types.enums import TradingPhase
from b_application.config.market_data_config import MarketHoursConfig

TAIWAN_TIMEZONE = ZoneInfo("Asia/Taipei")


class TaiwanMarketClock(IMarketClock):
    """
    Asia/Taipei wall clock and the regular TWSE/TPEX trading day on weekdays, at the times market_hours sets.

    TWSE and TPEx both take orders from 08:30, match the opening call auction at 09:00, trade continuously
    09:00-13:25, and run the closing call auction 13:25-13:30, which takes limit ROD orders only. Sources, read
    2026-10-31: the TWSE trading mechanism page (https://www.twse.com.tw/en/products/system/trading.html) and the
    TPEx trading system overview, sections 5 and 6 (https://www.tpex.org.tw/zh-tw/mainboard/trading/rules/system.html).
    """

    def __init__(self, hours: MarketHoursConfig) -> None:
        self._hours = hours
        # The phase that starts at each time of a weekday, latest first. Before the opening auction the market is CLOSED.
        self._trading_day = (
            (hours.close, TradingPhase.CLOSED),
            (hours.closing_auction_start, TradingPhase.CLOSING_AUCTION),
            (hours.continuous_start, TradingPhase.CONTINUOUS),
            (hours.opening_auction_start, TradingPhase.OPENING_AUCTION),
        )

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
    def session_close(self, session: date) -> datetime:
        return datetime.combine(session, self._hours.close, tzinfo=TAIWAN_TIMEZONE)

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
        day = moment.date() if moment.time() < self._hours.continuous_start else moment.date() + timedelta(days=1)
        opened = 0

        while True:
            if day.weekday() < 5:
                opened += 1

                if opened >= sessions:
                    return self.session_close(day)

            day += timedelta(days=1)

    @override
    def last_closed_session(self) -> date:
        now = self.now()
        day = now.date() if now.time() >= self._hours.close else now.date() - timedelta(days=1)

        while day.weekday() >= 5:
            day -= timedelta(days=1)

        return day

    @override
    def last_settled_session(self) -> date:
        now = self.now()
        day = now.date() if now.time() >= self._hours.settled else now.date() - timedelta(days=1)

        while day.weekday() >= 5:
            day -= timedelta(days=1)

        return day

    @override
    def trading_phase(self) -> TradingPhase:
        now = self.now()

        if now.weekday() >= 5:
            return TradingPhase.CLOSED

        return next((phase for start, phase in self._trading_day if now.time() >= start), TradingPhase.CLOSED)
