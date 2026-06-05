# backend/src/c_infrastructure/market/yahoo_finance_adapter.py

import asyncio
import math
import time
from datetime import datetime, timedelta
from typing import Any, cast

import pandas as pd
import yfinance as yf

from a_domain.model.market.ohlcv import Ohlcv
from a_domain.model.market.stock import Stock
from a_domain.ports.market.price_provider import IPriceProvider
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.types.enums import MarketType


# TODO: This file is dirty af. Needa clean it.
def format_yahoo_ticker(stock: Stock) -> str:
    if stock.market == MarketType.TPEX:
        return f"{stock.stock_id}.TWO"

    return f"{stock.stock_id}.TW"


def dataframe_to_bars(df: pd.DataFrame) -> list[Ohlcv]:
    if df.empty:
        return []

    required_columns = {"Open", "High", "Low", "Close", "Volume"}
    if not required_columns.issubset(df.columns):
        return []

    bars: list[Ohlcv] = []

    for index in range(len(df)):
        row = df.iloc[index]
        timestamp = pd.Timestamp(cast(Any, df.index[index]))

        if not isinstance(timestamp, pd.Timestamp):
            continue

        close = row["Close"]
        if pd.isna(close):
            continue

        close_value = float(close)
        adj_close = row.get("Adj Close")

        bars.append(
            Ohlcv(
                ts=timestamp.to_pydatetime(),
                open=float(row["Open"]) if not pd.isna(row["Open"]) else close_value,
                high=float(row["High"]) if not pd.isna(row["High"]) else close_value,
                low=float(row["Low"]) if not pd.isna(row["Low"]) else close_value,
                close=close_value,
                volume=int(row["Volume"]) if not pd.isna(row["Volume"]) else 0,
                adj_close=float(adj_close) if adj_close is not None and not pd.isna(adj_close) else None,
            )
        )

    return bars


class YahooFinanceProvider(IPriceProvider):
    def __init__(
        self,
        logger: ILoggingProvider,
        batch_size: int = 50,
        delay_seconds: float = 1.5,
    ):
        self._logger = logger
        self._batch_size = batch_size
        self._delay_seconds = delay_seconds

    async def fetch_history(
        self,
        stocks: list[Stock],
        start_date: datetime,
        end_date: datetime,
    ) -> dict[str, list[Ohlcv]]:
        stocks = self._remove_duplicates(stocks)

        if not stocks:
            return {}

        result: dict[str, list[Ohlcv]] = {}
        batches = self._split_batches(stocks)
        total_batches = len(batches)

        self._logger.info(f"Fetching Yahoo history: {len(stocks)} stocks, batch size={self._batch_size}, batches={total_batches}")

        completed_symbols = 0
        started_at = time.perf_counter()

        for batch_index, batch in enumerate(batches, start=1):
            batch_started_at = time.perf_counter()
            ticker_to_stock = {format_yahoo_ticker(stock): stock for stock in batch}

            self._logger.info(f"Yahoo history batch {batch_index}/{total_batches} started: {len(ticker_to_stock)} symbols")

            df = await self._download(
                tickers=list(ticker_to_stock.keys()),
                start_date=start_date,
                end_date=end_date + timedelta(days=1),
                interval="1d",
            )

            success_count = 0

            for ticker, stock in ticker_to_stock.items():
                stock_df = self._get_stock_dataframe(df, ticker)
                bars = dataframe_to_bars(stock_df)

                if bars:
                    result[stock.stock_id] = bars
                    success_count += 1

            completed_symbols += len(batch)
            failed_count = len(batch) - success_count
            elapsed = time.perf_counter() - batch_started_at
            total_elapsed = time.perf_counter() - started_at

            self._logger.info(
                f"Yahoo history batch {batch_index}/{total_batches} done: "
                f"success={success_count}, failed={failed_count}, "
                f"progress={completed_symbols}/{len(stocks)}, "
                f"elapsed={elapsed:.1f}s, total_elapsed={total_elapsed:.1f}s"
            )

            await asyncio.sleep(self._delay_seconds)

        self._logger.info(f"Yahoo history completed: {len(result)}/{len(stocks)} stocks returned data")
        return result

    async def fetch_realtime_bars(self, stocks: list[Stock]) -> dict[str, Ohlcv]:
        stocks = self._remove_duplicates(stocks)

        if not stocks:
            return {}

        result: dict[str, Ohlcv] = {}
        batches = self._split_batches(stocks)
        total_batches = len(batches)

        self._logger.info(f"Fetching Yahoo latest bars: {len(stocks)} stocks, batch size={self._batch_size}, batches={total_batches}")

        completed_symbols = 0
        started_at = time.perf_counter()

        for batch_index, batch in enumerate(batches, start=1):
            batch_started_at = time.perf_counter()
            ticker_to_stock = {format_yahoo_ticker(stock): stock for stock in batch}

            self._logger.info(f"Yahoo latest batch {batch_index}/{total_batches} started: {len(ticker_to_stock)} symbols")

            df = await self._download(
                tickers=list(ticker_to_stock.keys()),
                period="1d",
                interval="5m",
            )

            success_count = 0

            for ticker, stock in ticker_to_stock.items():
                stock_df = self._get_stock_dataframe(df, ticker)
                bars = dataframe_to_bars(stock_df)

                if bars:
                    result[stock.stock_id] = bars[-1]
                    success_count += 1

            completed_symbols += len(batch)
            failed_count = len(batch) - success_count
            elapsed = time.perf_counter() - batch_started_at
            total_elapsed = time.perf_counter() - started_at

            self._logger.info(
                f"Yahoo latest batch {batch_index}/{total_batches} done: "
                f"success={success_count}, failed={failed_count}, "
                f"progress={completed_symbols}/{len(stocks)}, "
                f"elapsed={elapsed:.1f}s, total_elapsed={total_elapsed:.1f}s"
            )

            await asyncio.sleep(self._delay_seconds)

        return result

    async def _download(
        self,
        tickers: list[str],
        interval: str,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        period: str | None = None,
    ) -> pd.DataFrame:
        def call_yahoo() -> object:
            return yf.download(
                tickers=tickers,
                start=start_date.strftime("%Y-%m-%d") if start_date else None,
                end=end_date.strftime("%Y-%m-%d") if end_date else None,
                period=period,
                interval=interval,
                group_by="ticker",
                auto_adjust=False,
                threads=True,
                progress=False,
            )

        downloaded = await asyncio.to_thread(call_yahoo)

        if isinstance(downloaded, pd.DataFrame):
            return downloaded

        return pd.DataFrame()

    def _get_stock_dataframe(self, df: pd.DataFrame, ticker: str) -> pd.DataFrame:
        if df.empty:
            return pd.DataFrame()

        if isinstance(df.columns, pd.MultiIndex):
            if ticker not in df.columns.get_level_values(0):
                return pd.DataFrame()

            stock_df = df[ticker]
            return stock_df if isinstance(stock_df, pd.DataFrame) else pd.DataFrame()

        return df

    def _split_batches(self, stocks: list[Stock]) -> list[list[Stock]]:
        if not stocks:
            return []

        batch_count = math.ceil(len(stocks) / self._batch_size)

        return [stocks[index * self._batch_size : (index + 1) * self._batch_size] for index in range(batch_count)]

    def _remove_duplicates(self, stocks: list[Stock]) -> list[Stock]:
        unique: dict[str, Stock] = {}

        for stock in stocks:
            unique[stock.stock_id] = stock

        return list(unique.values())
