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

        yf_tickers = " ".join([self._format_ticker(stock) for stock in stocks])

        def _fetch() -> Any:
            return yf.download(yf_tickers, period="1d", progress=False)

        try:
            self._logger.debug(f"Fetching realtime bars for {len(stocks)} stocks...")
            df = await asyncio.to_thread(_fetch)

            if not isinstance(df, pd.DataFrame) or df.empty:
                return {}

            result_map = {}
            for stock in stocks:
                ticker = self._format_ticker(stock)

                try:
                    if len(stocks) == 1:
                        row = df.iloc[-1]
                    else:
                        target_data = df.xs(ticker, axis=1, level=1)
                        if isinstance(target_data, (pd.DataFrame, pd.Series)):
                            row = target_data.iloc[-1]
                        else:
                            continue
                except (KeyError, AttributeError):
                    continue

                if pd.isna(row["Close"]):
                    continue

                result_map[stock.stock_id] = Ohlcv(
                    ts=df.index[-1].to_pydatetime(),  # type: ignore
                    open=float(row["Open"]),
                    high=float(row["High"]),
                    low=float(row["Low"]),
                    close=float(row["Close"]),
                    volume=int(row["Volume"]),
                )
            return result_map

        except Exception as e:
            self._logger.error(f"YFinance error fetching realtime bars: {e}")
            return {}
