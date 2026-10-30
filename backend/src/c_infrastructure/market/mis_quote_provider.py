import asyncio
import time
from datetime import datetime
from typing import Any

import httpx

from a_domain.model.market.ohlcv import Ohlcv
from a_domain.model.market.stock import Stock
from a_domain.ports.market.price_provider import IRealtimeQuoteProvider
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.types.enums import MarketType
from c_infrastructure.system.market_clock import TAIWAN_TIMEZONE

SHARES_PER_LOT = 1000


def parse_quotes(payload: dict[str, Any]) -> dict[str, Ohlcv]:
    """Each traded stock's quote in one getStockInfo.jsp response, by stock id. Raises when the API refused the request."""
    if payload.get("rtcode") != "0000":
        raise ValueError(f"TWSE MIS refused the request: rtcode {payload.get('rtcode')} {payload.get('rtmessage')}")

    return {item["c"]: quote for item in payload.get("msgArray", []) if (quote := parse_quote(item)) is not None}


def parse_quote(item: dict[str, Any]) -> Ohlcv | None:
    """
    The session so far, closing at the last trade and stamped with that trade's time.

    z and t are the last trade. When the latest update was not a trade, z is "-" and t is the update's time, so the
    trade object's z and t are used instead, as the exchange's own quote page does. A stock that has not traded this
    session has neither and gets no quote: a bid or an ask is not a price anyone paid.
    """
    last_trade = item.get("trade") or {}
    price, time_of_day = _number(item.get("z")), item.get("t")

    if price is None:
        price, time_of_day = _number(last_trade.get("z")), last_trade.get("t")

    if price is None or not item.get("c"):
        return None

    try:
        traded_at = datetime.strptime(f"{item.get('d')} {time_of_day}", "%Y%m%d %H:%M:%S").replace(tzinfo=TAIWAN_TIMEZONE)
    except ValueError:
        return None

    return Ohlcv(
        ts=traded_at,
        open=_number(item.get("o")) or price,
        high=_number(item.get("h")) or price,
        low=_number(item.get("l")) or price,
        close=price,
        volume=int(_number(item.get("v")) or 0) * SHARES_PER_LOT,
    )


def _number(text: Any) -> float | None:
    try:
        return float(text)
    except TypeError, ValueError:
        return None


class MisQuoteProvider(IRealtimeQuoteProvider):
    """Last trades of TWSE and TPEX stocks from the exchange's market information system (MIS), a few seconds behind."""

    URL = "https://mis.twse.com.tw/stock/api/getStockInfo.jsp"
    # 100 channels per request are answered; 200 are refused with rtcode 9999.
    BATCH_SIZE = 50
    TIMEOUT_SECONDS = 10.0

    def __init__(self, logger: ILoggingProvider, request_interval_seconds: float = 5.0) -> None:
        """
        request_interval_seconds: the API asks clients to wait its userDelay (5000 ms) between requests, and faster
        polling is reported to get the address blocked, so requests go one at a time at least this far apart.
        """
        self._logger = logger
        self._request_interval_seconds = request_interval_seconds
        self._last_request_at: float | None = None

    async def fetch_realtime_bars(self, stocks: list[Stock]) -> dict[str, Ohlcv]:
        channels = list(
            dict.fromkeys(f"{'otc' if stock.market == MarketType.TPEX else 'tse'}_{stock.stock_id}.tw" for stock in stocks)
        )
        quotes: dict[str, Ohlcv] = {}

        if not channels:
            return quotes

        async with httpx.AsyncClient(timeout=self.TIMEOUT_SECONDS) as client:
            for offset in range(0, len(channels), self.BATCH_SIZE):
                await self._wait_for_request_slot()
                params = {"ex_ch": "|".join(channels[offset : offset + self.BATCH_SIZE]), "json": "1", "delay": "0"}
                response = await client.get(self.URL, params=params)
                response.raise_for_status()
                quotes.update(parse_quotes(response.json()))

        requested = {stock.stock_id for stock in stocks}
        quotes = {stock_id: quote for stock_id, quote in quotes.items() if stock_id in requested}
        self._logger.info(f"TWSE MIS quotes: {len(quotes)}/{len(requested)} stocks with a trade")

        return quotes

    async def _wait_for_request_slot(self) -> None:
        if self._last_request_at is not None:
            await asyncio.sleep(max(0.0, self._request_interval_seconds - (time.monotonic() - self._last_request_at)))

        self._last_request_at = time.monotonic()
