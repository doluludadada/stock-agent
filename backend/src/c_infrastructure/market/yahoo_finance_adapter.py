import asyncio
from datetime import datetime
from typing import Any

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

    def _format_ticker(self, stock: Stock) -> str:
        if stock.market == MarketType.TPEX:
            return f"{stock.stock_id}.TWO"
        return f"{stock.stock_id}.TW"

    async def fetch_history(self, stock: Stock, start_date: datetime, end_date: datetime) -> list[Ohlcv]:
        yf_ticker = self._format_ticker(stock)

        def _fetch() -> Any:
            ticker = yf.Ticker(yf_ticker)
            return ticker.history(start=start_date.strftime("%Y-%m-%d"), end=end_date.strftime("%Y-%m-%d"))

        try:
            self._logger.debug(f"Fetching history for {yf_ticker} from Yahoo Finance...")
            df = await asyncio.to_thread(_fetch)

            if not isinstance(df, pd.DataFrame) or df.empty:
                return []

            bars = []
            for index, row in df.iterrows():
                bars.append(
                    Ohlcv(
                        ts=index.to_pydatetime(),  # type: ignore
                        open=float(row["Open"]),
                        high=float(row["High"]),
                        low=float(row["Low"]),
                        close=float(row["Close"]),
                        volume=int(row["Volume"]),
                    )
                )
            return bars

        except Exception as e:
            self._logger.error(f"YFinance error fetching history for {stock.stock_id}: {e}")
            return []

    async def fetch_realtime_bars(self, stocks: list[Stock]) -> dict[str, Ohlcv]:
        if not stocks:
            return {}

        result_map = {}
        self._logger.debug(f"Fetching realtime bars for {len(stocks)} stocks concurrently...")

        # Create a helper function for a single stock
        async def _fetch_single(stock: Stock):
            ticker_symbol = self._format_ticker(stock)

            def _get_data():
                return yf.Ticker(ticker_symbol).history(period="1d")

            try:
                df = await asyncio.to_thread(_get_data)
                if not df.empty:
                    row = df.iloc[-1]
                    # Check if close is NaN (using pandas isna)
                    if pd.isna(row.get("Close")):
                        return None

                    return stock.stock_id, Ohlcv(
                        ts=df.index[-1].to_pydatetime(),  # type: ignore
                        open=float(row["Open"]),
                        high=float(row["High"]),
                        low=float(row["Low"]),
                        close=float(row["Close"]),
                        volume=int(row["Volume"]),
                    )
            except Exception as e:
                self._logger.error(f"YFinance error for {stock.stock_id}: {e}")
            return None

        # Run all requests concurrently
        results = await asyncio.gather(*[_fetch_single(s) for s in stocks])

        for res in results:
            if res:
                result_map[res[0]] = res[1]

        return result_map
