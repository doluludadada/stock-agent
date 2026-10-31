# backend/src/c_infrastructure/market/yahoo_finance_adapter.py

import asyncio
import time
from datetime import datetime, timedelta
from typing import Any, cast, override

import pandas as pd
import yfinance as yf

from a_domain.model.market.ohlcv import Ohlcv
from a_domain.model.market.stock import Stock
from a_domain.ports.market.yahoo_price_history_provider import IYahooPriceHistoryProvider
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.system.market_clock import IMarketClock
from a_domain.types.enums import MarketType
from b_application.config.market_data_config import MarketDataConfig


class YahooFinanceProvider(IYahooPriceHistoryProvider):
    def __init__(self, market_clock: IMarketClock, market_data: MarketDataConfig, logger: ILoggingProvider):
        self._clock = market_clock
        self._batch_size = market_data.history_batch_size
        self._delay_seconds = market_data.history_batch_delay_seconds
        self._logger = logger

    @override
    async def fetch_history(self, stocks: list[Stock], start_date: datetime, end_date: datetime) -> dict[str, list[Ohlcv]]:
        bars_by_stock = await self.download_bars(
            stocks, start=start_date.strftime("%Y-%m-%d"), end=(end_date + timedelta(days=1)).strftime("%Y-%m-%d")
        )
        # Yahoo emits a flat zero-volume bar for days the market was closed, such as typhoon days.
        traded = {stock_id: [bar for bar in bars if bar.volume > 0] for stock_id, bars in bars_by_stock.items()}
        return {stock_id: bars for stock_id, bars in traded.items() if bars}

    @override
    async def download_bars(self, stocks: list[Stock], start: str, end: str) -> dict[str, list[Ohlcv]]:
        unique_stocks = list({stock.stock_id: stock for stock in stocks}.values())
        bars_by_stock: dict[str, list[Ohlcv]] = {}
        started_at = time.perf_counter()

        for offset in range(0, len(unique_stocks), self._batch_size):
            batch = unique_stocks[offset : offset + self._batch_size]
            bars_by_stock.update(await self.download_batch(batch, start, end))
            self._logger.info(
                f"Yahoo daily bars: {offset + len(batch)}/{len(unique_stocks)} stocks requested, "
                f"{len(bars_by_stock)} with data, elapsed={time.perf_counter() - started_at:.1f}s"
            )
            await asyncio.sleep(self._delay_seconds)

        return bars_by_stock

    @override
    async def download_batch(self, stocks: list[Stock], start: str, end: str) -> dict[str, list[Ohlcv]]:
        stock_id_by_ticker = {
            f"{stock.stock_id}.{'TWO' if stock.market == MarketType.TPEX else 'TW'}": stock.stock_id for stock in stocks
        }
        download = await asyncio.to_thread(
            yf.download,
            tickers=list(stock_id_by_ticker),
            start=start,
            end=end,
            interval="1d",
            group_by="ticker",
            multi_level_index=True,
            auto_adjust=False,
            threads=True,
            progress=False,
        )
        return {stock_id: bars for ticker, stock_id in stock_id_by_ticker.items() if (bars := self.to_bars(download, ticker))}

    @override
    def to_bars(self, download: Any, ticker: str) -> list[Ohlcv]:
        if download is None or ticker not in download.columns.get_level_values(0):
            return []

        frame = cast(pd.DataFrame, download[ticker]).dropna(subset=["Close"])
        close = frame["Close"]
        frame = frame.fillna({"Open": close, "High": close, "Low": close, "Volume": 0})

        return [
            Ohlcv(
                ts=self._clock.session_close(row["ts"].date()),
                open=row["Open"],
                high=row["High"],
                low=row["Low"],
                close=row["Close"],
                volume=row["Volume"],
                adj_close=None if pd.isna(row["Adj Close"]) else row["Adj Close"],
            )
            for row in frame.rename_axis("ts").reset_index().to_dict("records")
        ]
