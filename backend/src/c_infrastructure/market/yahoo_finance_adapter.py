import asyncio
from datetime import datetime, timedelta

import pandas as pd
import yfinance as yf

from a_domain.model.market.ohlcv import Ohlcv
from a_domain.model.market.stock import Stock
from a_domain.ports.market.price_provider import IPriceProvider
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.types.enums import MarketType


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

    # Avoid pd.to_datetime(timestamp) inside iterrows().
    # Pylance sees iterrows() index as Hashable, which causes your error.
    timestamps = pd.DatetimeIndex(df.index).to_pydatetime()

    for i in range(len(df)):
        row = df.iloc[i]

        close = row["Close"]
        if pd.isna(close):
            continue

        close_value = float(close)
        adj_close = row.get("Adj Close")

        bars.append(
            Ohlcv(
                ts=timestamps[i],
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
    """
    Yahoo Finance provider.

    Main rule:
    - Do not call Yahoo once per stock.
    - Use yf.download() with ticker batches.
    """

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

        self._logger.info(f"Fetching Yahoo history: {len(stocks)} stocks, batch size={self._batch_size}")

        for batch in self._split_batches(stocks):
            ticker_to_stock = {format_yahoo_ticker(stock): stock for stock in batch}

            # yfinance end date is exclusive, so add 1 day.
            df = await self._download(
                tickers=list(ticker_to_stock.keys()),
                start_date=start_date,
                end_date=end_date + timedelta(days=1),
                interval="1d",
            )

            for ticker, stock in ticker_to_stock.items():
                stock_df = self._get_stock_dataframe(df, ticker)
                bars = dataframe_to_bars(stock_df)

                if bars:
                    result[stock.stock_id] = bars

            await asyncio.sleep(self._delay_seconds)

        self._logger.info(f"Yahoo history completed: {len(result)}/{len(stocks)} stocks returned data")
        return result

    async def fetch_realtime_bars(self, stocks: list[Stock]) -> dict[str, Ohlcv]:
        """
        Yahoo is not true realtime.

        This returns the latest available 5-minute bar.
        Use it only for your reduced candidate list, not full-market scanning.
        """
        stocks = self._remove_duplicates(stocks)

        if not stocks:
            return {}

        result: dict[str, Ohlcv] = {}

        self._logger.debug(f"Fetching Yahoo latest bars: {len(stocks)} stocks")

        for batch in self._split_batches(stocks):
            ticker_to_stock = {format_yahoo_ticker(stock): stock for stock in batch}

            df = await self._download(
                tickers=list(ticker_to_stock.keys()),
                period="1d",
                interval="5m",
            )

            for ticker, stock in ticker_to_stock.items():
                stock_df = self._get_stock_dataframe(df, ticker)
                bars = dataframe_to_bars(stock_df)

                if bars:
                    result[stock.stock_id] = bars[-1]

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
                threads=False,
                progress=False,
            )

        try:
            data = await asyncio.to_thread(call_yahoo)

            if isinstance(data, pd.DataFrame):
                return data

            return pd.DataFrame()

        except Exception as e:
            self._logger.warning(f"Yahoo download failed. tickers={len(tickers)}, error={e}")
            return pd.DataFrame()

    def _get_stock_dataframe(self, df: pd.DataFrame, ticker: str) -> pd.DataFrame:
        if df.empty:
            return pd.DataFrame()

        # Single ticker result.
        if not isinstance(df.columns, pd.MultiIndex):
            return df.copy()

        # Multiple ticker result with group_by="ticker".
        if ticker not in df.columns.get_level_values(0):
            return pd.DataFrame()

        selected = df.xs(ticker, axis=1, level=0, drop_level=True)

        if isinstance(selected, pd.Series):
            return selected.to_frame().T

        return selected.copy()

    def _split_batches(self, stocks: list[Stock]) -> list[list[Stock]]:
        return [stocks[i : i + self._batch_size] for i in range(0, len(stocks), self._batch_size)]

    def _remove_duplicates(self, stocks: list[Stock]) -> list[Stock]:
        seen: set[str] = set()
        result: list[Stock] = []

        for stock in stocks:
            if stock.stock_id in seen:
                continue

            seen.add(stock.stock_id)
            result.append(stock)

        return result
