import asyncio
import time
from datetime import datetime
from typing import Any, override

import httpx

from a_domain.model.market.ohlcv import Ohlcv
from a_domain.model.market.stock import Stock
from a_domain.ports.market.mis_quote_provider import IMisQuoteProvider
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.types.enums import MarketType
from b_application.config.market_data_config import MarketDataConfig
from b_application.config.sources_config import ExchangeSources
from c_infrastructure.system.market_clock import TAIWAN_TIMEZONE

SHARES_PER_LOT = 1000


class MisQuoteProvider(IMisQuoteProvider):
    """Last trades of TWSE and TPEX stocks from the exchange's market information system (MIS), a few seconds behind."""

    def __init__(self, exchange: ExchangeSources, market_data: MarketDataConfig, logger: ILoggingProvider) -> None:
        """
        market_data.quote_request_interval_seconds: the API asks clients to wait its userDelay (5000 ms) between requests,
        and faster polling is reported to get the address blocked, so requests go one at a time at least this far apart.
        """
        self._url = exchange.mis_quotes_url
        self._batch_size = market_data.quote_batch_size
        self._timeout_seconds = market_data.quote_timeout_seconds
        self._request_interval_seconds = market_data.quote_request_interval_seconds
        self._logger = logger
        self._last_request_at: float | None = None

    @override
    async def fetch_realtime_bars(self, stocks: list[Stock]) -> dict[str, Ohlcv]:
        channels = list(
            dict.fromkeys(f"{'otc' if stock.market == MarketType.TPEX else 'tse'}_{stock.stock_id}.tw" for stock in stocks)
        )
        quotes: dict[str, Ohlcv] = {}

        if not channels:
            return quotes

        async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
            for offset in range(0, len(channels), self._batch_size):
                await self.wait_for_request_slot()
                params = {"ex_ch": "|".join(channels[offset : offset + self._batch_size]), "json": "1", "delay": "0"}
                response = await client.get(self._url, params=params)
                response.raise_for_status()
                quotes.update(self.parse_quotes(response.json()))

        requested = {stock.stock_id for stock in stocks}
        quotes = {stock_id: quote for stock_id, quote in quotes.items() if stock_id in requested}
        self._logger.info(f"TWSE MIS quotes: {len(quotes)}/{len(requested)} stocks with a trade")

        return quotes

    @override
    def parse_quotes(self, payload: dict[str, Any]) -> dict[str, Ohlcv]:
        if payload.get("rtcode") != "0000":
            raise ValueError(f"TWSE MIS refused the request: rtcode {payload.get('rtcode')} {payload.get('rtmessage')}")

        return {item["c"]: quote for item in payload.get("msgArray", []) if (quote := self.parse_quote(item)) is not None}

    @override
    def parse_quote(self, item: dict[str, Any]) -> Ohlcv | None:
        last_trade = item.get("trade") or {}
        price, time_of_day = self.parse_number(item.get("z")), item.get("t")

        if price is None:
            price, time_of_day = self.parse_number(last_trade.get("z")), last_trade.get("t")

        if price is None or not item.get("c"):
            return None

        try:
            traded_at = datetime.strptime(f"{item.get('d')} {time_of_day}", "%Y%m%d %H:%M:%S").replace(tzinfo=TAIWAN_TIMEZONE)
        except ValueError:
            return None

        return Ohlcv(
            ts=traded_at,
            open=self.parse_number(item.get("o")) or price,
            high=self.parse_number(item.get("h")) or price,
            low=self.parse_number(item.get("l")) or price,
            close=price,
            volume=int(self.parse_number(item.get("v")) or 0) * SHARES_PER_LOT,
        )

    @override
    def parse_number(self, text: Any) -> float | None:
        try:
            return float(text)
        except TypeError, ValueError:
            return None

    @override
    async def wait_for_request_slot(self) -> None:
        if self._last_request_at is not None:
            await asyncio.sleep(max(0.0, self._request_interval_seconds - (time.monotonic() - self._last_request_at)))

        self._last_request_at = time.monotonic()
