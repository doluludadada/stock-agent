# backend/src/c_infrastructure/market/yahoo_finance_adapter.py

import asyncio
import time
from datetime import datetime, timedelta
from typing import cast

import pandas as pd
import yfinance as yf

from a_domain.model.market.ohlcv import Ohlcv
from a_domain.model.market.stock import Stock
from a_domain.ports.market.price_provider import IOhlcvProvider
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.types.enums import MarketType


class YahooFinanceProvider(IOhlcvProvider):
    def __init__(self, logger: ILoggingProvider, batch_size: int = 50, delay_seconds: float = 1.5):
        self._logger = logger
        self._batch_size = batch_size
        self._delay_seconds = delay_seconds

    async def fetch_history(self, stocks: list[Stock], start_date: datetime, end_date: datetime) -> dict[str, list[Ohlcv]]:
        bars_by_stock = await self._download_bars(
            stocks, "1d", start=start_date.strftime("%Y-%m-%d"), end=(end_date + timedelta(days=1)).strftime("%Y-%m-%d")
        )
        # Yahoo emits a flat zero-volume bar for days the market was closed, such as typhoon days.
        traded = {stock_id: [bar for bar in bars if bar.volume > 0] for stock_id, bars in bars_by_stock.items()}
        return {stock_id: bars for stock_id, bars in traded.items() if bars}

    async def fetch_realtime_bars(self, stocks: list[Stock]) -> dict[str, Ohlcv]:
        bars_by_stock = await self._download_bars(stocks, "5m", period="1d")
        return {stock_id: bars[-1] for stock_id, bars in bars_by_stock.items()}

    async def _download_bars(
        self, stocks: list[Stock], interval: str, start: str | None = None, end: str | None = None, period: str | None = None
    ) -> dict[str, list[Ohlcv]]:
        unique_stocks = list({stock.stock_id: stock for stock in stocks}.values())
        bars_by_stock: dict[str, list[Ohlcv]] = {}
        started_at = time.perf_counter()

        for offset in range(0, len(unique_stocks), self._batch_size):
            batch = unique_stocks[offset : offset + self._batch_size]
            stock_id_by_ticker = {
                f"{stock.stock_id}.{'TWO' if stock.market == MarketType.TPEX else 'TW'}": stock.stock_id for stock in batch
            }
            download = await asyncio.to_thread(
                yf.download,
                tickers=list(stock_id_by_ticker),
                start=start,
                end=end,
                period=period,
                interval=interval,
                group_by="ticker",
                multi_level_index=True,
                auto_adjust=False,
                threads=True,
                progress=False,
            )

            for ticker, stock_id in stock_id_by_ticker.items():
                if bars := _to_bars(download, ticker):
                    bars_by_stock[stock_id] = bars

            self._logger.info(
                f"Yahoo {interval} bars: {offset + len(batch)}/{len(unique_stocks)} stocks requested, "
                f"{len(bars_by_stock)} with data, elapsed={time.perf_counter() - started_at:.1f}s"
            )
            await asyncio.sleep(self._delay_seconds)

        return bars_by_stock


def _to_bars(download: pd.DataFrame | None, ticker: str) -> list[Ohlcv]:
    if download is None or ticker not in download.columns.get_level_values(0):
        return []

    frame = cast(pd.DataFrame, download[ticker]).dropna(subset=["Close"])
    close = frame["Close"]
    frame = frame.fillna({"Open": close, "High": close, "Low": close, "Volume": 0})

    return [
        Ohlcv(
            ts=row["ts"].to_pydatetime(),
            open=row["Open"],
            high=row["High"],
            low=row["Low"],
            close=row["Close"],
            volume=row["Volume"],
            adj_close=None if pd.isna(row["Adj Close"]) else row["Adj Close"],
        )
        for row in frame.rename_axis("ts").reset_index().to_dict("records")
    ]
