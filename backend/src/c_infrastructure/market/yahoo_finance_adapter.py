import asyncio
from datetime import datetime

import pandas as pd
import yfinance as yf

from a_domain.model.market.ohlcv import Ohlcv
from a_domain.ports.market.price_provider import IPriceProvider
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.types.enums import MarketType


class YahooFinanceProvider(IPriceProvider):
    """
    Fetches historical and realtime OHLCV data using yfinance.
    """

    def __init__(self, logger: ILoggingProvider):
        self._logger = logger

    def _format_ticker(self, stock_id: str) -> str:
        # 實務上可以透過傳入 MarketType 判斷 .TW 或 .TWO
        return f"{stock_id}.TW"

    async def fetch_history(self, stock_id: str, start_date: datetime, end_date: datetime) -> list[Ohlcv]:
        yf_ticker = self._format_ticker(stock_id)

        def _fetch():
            ticker = yf.Ticker(yf_ticker)
            return ticker.history(start=start_date.strftime("%Y-%m-%d"), end=end_date.strftime("%Y-%m-%d"))

        try:
            self._logger.debug(f"Fetching history for {yf_ticker} from Yahoo Finance...")
            df = await asyncio.to_thread(_fetch)

            if df.empty:
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
            self._logger.error(f"YFinance error fetching history for {stock_id}: {e}")
            return []

    async def fetch_realtime_bars(self, stock_ids: list[str]) -> dict[str, Ohlcv]:
        if not stock_ids:
            return {}

        yf_tickers = " ".join([self._format_ticker(sid) for sid in stock_ids])

        def _fetch():
            return yf.download(yf_tickers, period="1d", progress=False)

        try:
            self._logger.debug(f"Fetching realtime bars for {len(stock_ids)} stocks...")
            df = await asyncio.to_thread(_fetch)

            result_map = {}
            for stock_id in stock_ids:
                ticker = self._format_ticker(stock_id)

                try:
                    if len(stock_ids) == 1:
                        row = df.iloc[-1]
                    else:
                        row = df.xs(ticker, axis=1, level=1).iloc[-1]
                except KeyError:
                    continue

                if pd.isna(row["Close"]):
                    continue

                result_map[stock_id] = Ohlcv(
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
