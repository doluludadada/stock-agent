import asyncio
import re
import time
from collections.abc import Collection, Mapping
from datetime import date, timedelta
from typing import Any, override

import httpx

from a_domain.model.market.ohlcv import Ohlcv
from a_domain.ports.market.daily_history_source import IDailyHistorySource
from a_domain.ports.market.taiwan_stock_provider import ITaiwanStockProvider
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.system.market_clock import IMarketClock
from a_domain.types.enums import MarketType
from b_application.config.market_data_config import MarketDataConfig
from b_application.config.sources_config import DailyReportFeed, ExRightReferenceFeed
from c_infrastructure.market.twse_provider import ROC_YEAR_OFFSET, STOCK_CODE_LENGTH


class ExchangeDailyReports(IDailyHistorySource):
    """
    The exchanges' own reports of each date on their sites (sources.exchange.daily_reports), measured on 2026-11-07:
    TWSE's MI_INDEX and TPEX's closing quotes list every security of one session, and per month TWSE's MI_5MINS_HIST and
    TPEX's index report give the index's prices, and TWSE's FMTQIK and TPEX's trading index report the market's volume
    and the index's change. TWSE's TWT49U and TPEX's exDailyQ (sources.exchange.ex_right_references) list the ex-right
    and ex-dividend references of a range of dates, in ROC dates; TWSE's mark the year, the month and the day with a
    character each. A date without a session, or a range without an ex-day, answers no rows: TWSE says so in `stat`,
    TPEX serves an empty table. An answer of another date than the one asked counts as none. TWSE also refuses a range
    in `stat`, without a table: any answer of the ex-right references that has no table and is not its `empty_stat` raises.

    TWSE refuses an address for minutes after more than about 3 requests in 5 seconds. So a request to one site waits
    until market_data.history_request_interval_seconds after the request to it before, whichever runtime made that one:
    `request_slots` is the process's time of each site's latest request, which a request reserves before it waits.
    """

    def __init__(
        self,
        feeds: Mapping[MarketType, DailyReportFeed],
        ex_right_feed: ExRightReferenceFeed,
        listing: ITaiwanStockProvider,
        request_slots: dict[MarketType, float],
        market_clock: IMarketClock,
        market_data: MarketDataConfig,
        board_lot_shares: int,
        logger: ILoggingProvider,
    ) -> None:
        self._feeds = feeds
        self._ex_right_feed = ex_right_feed
        self._listing = listing
        self._request_slots = request_slots
        self._clock = market_clock
        self._interval_seconds = market_data.history_request_interval_seconds
        self._timeout_seconds = market_data.history_timeout_seconds
        self._board_lot_shares = board_lot_shares
        self._logger = logger

    @override
    async def session_bars(self, session: date) -> dict[str, Ohlcv]:
        bars: dict[str, Ohlcv] = {}

        for market, feed in self._feeds.items():
            served = self.quotes(await self.get(market, feed.quotes_url.format(date=session)), market, session)

            if not served:
                self._logger.info(f"Exchange reports of {session}: {market.value} lists no quote of it")
                return {}

            bars |= served

        self._logger.info(f"Exchange reports of {session}: {len(bars)} stocks with a trade")
        return bars

    @override
    async def index_bars(self, market: MarketType, first: date, last: date) -> list[Ohlcv]:
        feed, month, bars = self._feeds[market], first.replace(day=1), []

        while month <= last:
            prices = await self.get(market, feed.index_prices_url.format(date=month))
            volumes = await self.get(market, feed.index_volume_url.format(date=month))
            bars += [bar for bar in self.index_month(prices, volumes, market) if first <= self._clock.to_trading_date(bar.ts) <= last]
            month = (month + timedelta(days=31)).replace(day=1)

        self._logger.info(f"Exchange index bars of {market.value} from {first} to {last}: {len(bars)} sessions")
        return sorted(bars, key=lambda bar: bar.ts)

    @override
    async def ex_right_references(self, market: MarketType, first: date, last: date) -> dict[tuple[str, date], float]:
        report = self._ex_right_feed.reports[market]
        answer = await self.get(market, report.url.format(first=first, last=last))

        if report.empty_stat is not None and answer.get("stat") == report.empty_stat:
            return {}

        references: dict[tuple[str, date], float] = {}

        for row in self.rows(answer, [report.date, report.stock_id, report.reference]):
            session = self.session_date("/".join(re.findall(r"\d+", row[report.date])))
            price = self._listing.parse_number(row[report.reference])

            if session is not None and price is not None and price > 0 and len(row[report.stock_id]) == STOCK_CODE_LENGTH:
                references[(row[report.stock_id], session)] = price

        self._logger.info(f"{market.value.upper()} ex-right references from {first} to {last}: {len(references)}")
        return references

    @override
    async def get(self, market: MarketType, url: str) -> Any:
        now = time.monotonic()
        slot = max(now, self._request_slots.get(market, now - self._interval_seconds) + self._interval_seconds)
        self._request_slots[market] = slot
        await asyncio.sleep(slot - now)

        async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
            response = await client.get(url)
            response.raise_for_status()
            return response.json()

    @override
    def rows(self, answer: Any, fields: Collection[str]) -> list[dict[str, str]]:
        for table in answer.get("tables") or [answer]:
            names = [str(name).strip() for name in table.get("fields") or []]

            if set(fields) <= set(names):
                return [dict(zip(names, (str(value).strip() for value in row), strict=False)) for row in table.get("data") or []]

        raise ValueError(f"The report ({answer.get('stat', 'no stat')}) has no table of the fields {', '.join(fields)}")

    @override
    def quotes(self, answer: Any, market: MarketType, session: date) -> dict[str, Ohlcv]:
        """TWSE's answer names its date only when it holds the session, TPEX's always."""
        if answer.get("date") != f"{session:%Y%m%d}":
            return {}

        fields, stamp, bars = self._feeds[market].quote_fields, self._clock.session_close(session), {}
        names = [fields.open, fields.high, fields.low, fields.close]

        for row in self.rows(answer, [fields.stock_id, *names, fields.volume, fields.change, *filter(None, [fields.sign])]):
            open_price, high, low, close = (self._listing.parse_number(row[name]) or 0.0 for name in names)
            volume = self._listing.parse_number(row[fields.volume])

            if len(row[fields.stock_id]) != STOCK_CODE_LENGTH or volume is None or min(open_price, high, low, close) <= 0:
                continue

            change = self.change(row[fields.sign] if fields.sign else "", row[fields.change], close)
            bars[row[fields.stock_id]] = Ohlcv(
                ts=stamp, open=open_price, high=high, low=low, close=close, volume=int(volume), change=change
            )

        return bars

    @override
    def change(self, sign: str, text: str, close: float) -> float | None:
        """TWSE's sign is HTML such as `<p style= color:green>-</p>`, or `<p>X</p>` where it compared to no reference."""
        sign = re.sub(r"<[^>]*>", "", sign).strip()

        if sign == "X":
            return None

        return self._listing.parse_change(f"{sign if sign in ('+', '-') else ''}{text}", close)

    @override
    def index_month(self, prices: Any, volumes: Any, market: MarketType) -> list[Ohlcv]:
        feed = self._feeds[market]
        price_fields, volume_fields = feed.index_price_fields, feed.index_volume_fields
        unit = self._board_lot_shares if feed.index_volume_lots else 1
        number = self._listing.parse_number
        served = {str(name).strip() for table in volumes.get("tables") or [volumes] for name in table.get("fields") or []}
        earlier = volume_fields.earlier_volume if volume_fields.volume not in served else None
        volume_name = earlier or volume_fields.volume
        traded = {
            self.session_date(row[volume_fields.date]): (number(row[volume_name]), number(row[volume_fields.change]))
            for row in self.rows(volumes, [volume_fields.date, volume_name, volume_fields.change])
        }
        names = [price_fields.open, price_fields.high, price_fields.low, price_fields.close]
        bars = []

        for row in self.rows(prices, [price_fields.date, *names]):
            session = self.session_date(row[price_fields.date])
            open_price, high, low, close = (number(row[name]) or 0.0 for name in names)
            volume, change = traded.get(session, (None, None))

            if session is not None and volume is not None and min(open_price, high, low, close) > 0:
                stamp, shares = self._clock.session_close(session), round(volume * unit)
                bars.append(Ohlcv(ts=stamp, open=open_price, high=high, low=low, close=close, volume=shares, change=change))

        return bars

    @override
    def session_date(self, text: str) -> date | None:
        try:
            year, month, day = (int(part) for part in text.split("/"))
            return date(year + ROC_YEAR_OFFSET if year < ROC_YEAR_OFFSET else year, month, day)
        except ValueError:
            return None
