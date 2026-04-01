import asyncio
from datetime import datetime

import pandas as pd
import yfinance as yf

from a_domain.model.market.ohlcv import Ohlcv
from a_domain.model.market.stock import Stock
from a_domain.ports.market.price_provider import IPriceProvider
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.types.enums import MarketType


class YahooFinanceProvider(IPriceProvider):
    """
    Fetches historical and realtime OHLCV data using yfinance.
    """

    def __init__(self, logger: ILoggingProvider):
        self._logger = logger
        # Protect Yahoo Finance IP bans
        self._api_semaphore = asyncio.Semaphore(15)

    def _format_ticker(self, stock: Stock) -> str:
        if stock.market == MarketType.TPEX:
            return f"{stock.stock_id}.TWO"
        return f"{stock.stock_id}.TW"

    # ------------------------------------------------------------------------ #
    #                               Historical Data                            #
    # ------------------------------------------------------------------------ #

    async def _fetch_single_history(self, stock: Stock, start_date: datetime, end_date: datetime) -> tuple[str, list[Ohlcv]]:
        """Private method to handle the API call for a single stock."""
        yf_ticker = self._format_ticker(stock)

        def _get():
            return yf.Ticker(yf_ticker).history(start=start_date.strftime("%Y-%m-%d"), end=end_date.strftime("%Y-%m-%d"))

        try:
            async with self._api_semaphore:
                df = await asyncio.to_thread(_get)

            if not isinstance(df, pd.DataFrame) or df.empty:
                return stock.stock_id, []

            bars: list[Ohlcv] = []

            # Safely extract DatetimeIndex to an array of native Python datetimes
            dates = pd.to_datetime(df.index).to_pydatetime()

            for i in range(len(df)):
                row = df.iloc[i]
                bars.append(
                    Ohlcv(
                        ts=dates[i],
                        open=float(row["Open"]),
                        high=float(row["High"]),
                        low=float(row["Low"]),
                        close=float(row["Close"]),
                        volume=int(row["Volume"]),
                    )
                )
            return stock.stock_id, bars

        except Exception as e:
            self._logger.error(f"YFinance error for {stock.stock_id}: {e}")
            return stock.stock_id, []

    async def fetch_history(self, stocks: list[Stock], start_date: datetime, end_date: datetime) -> dict[str, list[Ohlcv]]:
        """Public method to orchestrate concurrent fetching with progress logging."""
        result_map: dict[str, list[Ohlcv]] = {}
        total = len(stocks)
        completed = 0
        failed = 0

        self._logger.info(f"Fetching price history for {total} stocks (semaphore={self._api_semaphore._value})...")

        async def _tracked_fetch(stock: Stock) -> tuple[str, list[Ohlcv]]:
            nonlocal completed, failed
            sid, bars = await self._fetch_single_history(stock, start_date, end_date)
            completed += 1
            if not bars:
                failed += 1
            if completed % 50 == 0 or completed == total:
                self._logger.info(f"  Progress: {completed}/{total} fetched ({failed} empty)")
            return sid, bars

        tasks = [_tracked_fetch(s) for s in stocks]
        results = await asyncio.gather(*tasks)

        for sid, bars in results:
            if bars:
                result_map[sid] = bars

        self._logger.info(f"Fetch complete: {len(result_map)}/{total} stocks have valid price data.")
        return result_map

    # ------------------------------------------------------------------------ #
    #                               Realtime Data                              #
    # ------------------------------------------------------------------------ #

    async def _fetch_single_realtime(self, stock: Stock) -> tuple[str, Ohlcv] | None:
        """Private method to handle realtime API call for a single stock."""
        ticker_symbol = self._format_ticker(stock)

        def _get_data():
            return yf.Ticker(ticker_symbol).history(period="1d")

        try:
            async with self._api_semaphore:
                df = await asyncio.to_thread(_get_data)

            if not df.empty:
                row = df.iloc[-1]
                if pd.isna(row.get("Close")):
                    return None

                # Safely extract the single timestamp
                ts_obj = pd.to_datetime(df.index[-1]).to_pydatetime()

                bar = Ohlcv(
                    ts=ts_obj,
                    open=float(row["Open"]),
                    high=float(row["High"]),
                    low=float(row["Low"]),
                    close=float(row["Close"]),
                    volume=int(row["Volume"]),
                )
                return stock.stock_id, bar

        except Exception as e:
            self._logger.error(f"YFinance error for {stock.stock_id}: {e}")

        return None

    async def fetch_realtime_bars(self, stocks: list[Stock]) -> dict[str, Ohlcv]:
        """Public method to orchestrate concurrent realtime fetching."""
        if not stocks:
            return {}

        result_map: dict[str, Ohlcv] = {}
        self._logger.debug(f"Fetching realtime bars for {len(stocks)} stocks concurrently...")

        tasks = [self._fetch_single_realtime(s) for s in stocks]
        results = await asyncio.gather(*tasks)

        for res in results:
            if res:
                result_map[res[0]] = res[1]

        return result_map
