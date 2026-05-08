from datetime import datetime

from sqlmodel import col, select

from a_domain.model.market.ohlcv import Ohlcv
from a_domain.model.market.stock import Stock
from a_domain.ports.market.price_provider import IPriceProvider
from a_domain.ports.system.logging_provider import ILoggingProvider
from c_infrastructure.database.db_connector import DatabaseConnector
from c_infrastructure.database.models.ohlcv_dto import OhlcvDTO


class CachedPriceProvider(IPriceProvider):
    """
    Cache wrapper for price data.

    Simple behavior:
    1. Load cache once.
    2. Find stocks with missing/incomplete cache.
    3. Fetch missing stocks in one fallback call.
    4. Save fetched bars.
    5. Return sorted cached + fresh bars.
    """

    def __init__(
        self,
        fallback_provider: IPriceProvider,
        db: DatabaseConnector,
        logger: ILoggingProvider,
    ):
        self._fallback = fallback_provider
        self._db = db
        self._logger = logger

    async def fetch_realtime_bars(self, stocks: list[Stock]) -> dict[str, Ohlcv]:
        # Keep this simple.
        # YahooFinanceProvider already batches the request.
        return await self._fallback.fetch_realtime_bars(stocks)

    async def fetch_history(
        self,
        stocks: list[Stock],
        start_date: datetime,
        end_date: datetime,
    ) -> dict[str, list[Ohlcv]]:
        stocks = self._remove_duplicates(stocks)

        if not stocks:
            return {}

        stock_ids = [stock.stock_id for stock in stocks]

        cached_bars: dict[str, list[Ohlcv]] = {}

        async with self._db.get_session() as session:
            stmt = (
                select(OhlcvDTO)
                .where(col(OhlcvDTO.stock_id).in_(stock_ids))
                .where(col(OhlcvDTO.ts) >= start_date)
                .where(col(OhlcvDTO.ts) <= end_date)
                .order_by(col(OhlcvDTO.stock_id), col(OhlcvDTO.ts))
            )

            result = await session.execute(stmt)
            records = result.scalars().all()

        for record in records:
            cached_bars.setdefault(record.stock_id, []).append(
                Ohlcv(
                    ts=record.ts,
                    open=record.open,
                    high=record.high,
                    low=record.low,
                    close=record.close,
                    volume=record.volume,
                    adj_close=record.adj_close,
                )
            )

        missing_stocks = self._find_missing_stocks(stocks, cached_bars, start_date, end_date)

        if missing_stocks:
            self._logger.info(f"History cache miss: {len(missing_stocks)}/{len(stocks)} stocks")

            fresh_bars = await self._fallback.fetch_history(
                missing_stocks,
                start_date,
                end_date,
            )

            await self._save_bars(fresh_bars)

            for stock_id, bars in fresh_bars.items():
                cached_bars.setdefault(stock_id, []).extend(bars)

        return self._clean_result(cached_bars)

    def _find_missing_stocks(
        self,
        stocks: list[Stock],
        cached_bars: dict[str, list[Ohlcv]],
        start_date: datetime,
        end_date: datetime,
    ) -> list[Stock]:
        missing: list[Stock] = []

        for stock in stocks:
            bars = cached_bars.get(stock.stock_id, [])

            if not bars:
                missing.append(stock)
                continue

            first_date = min(bar.ts.date() for bar in bars)
            last_date = max(bar.ts.date() for bar in bars)

            if first_date > start_date.date() or last_date < end_date.date():
                missing.append(stock)

        return missing

    async def _save_bars(self, bars_by_stock: dict[str, list[Ohlcv]]) -> None:
        if not bars_by_stock:
            return

        saved_count = 0

        async with self._db.get_session() as session:
            for stock_id, bars in bars_by_stock.items():
                for bar in bars:
                    await session.merge(
                        OhlcvDTO(
                            stock_id=stock_id,
                            ts=bar.ts,
                            open=bar.open,
                            high=bar.high,
                            low=bar.low,
                            close=bar.close,
                            volume=bar.volume,
                            adj_close=bar.adj_close,
                        )
                    )
                    saved_count += 1

            await session.commit()

        self._logger.debug(f"Saved {saved_count} OHLCV bars to cache")

    def _clean_result(self, bars_by_stock: dict[str, list[Ohlcv]]) -> dict[str, list[Ohlcv]]:
        result: dict[str, list[Ohlcv]] = {}

        for stock_id, bars in bars_by_stock.items():
            unique_bars = {bar.ts: bar for bar in bars}
            sorted_bars = sorted(unique_bars.values(), key=lambda bar: bar.ts)

            if sorted_bars:
                result[stock_id] = sorted_bars

        return result

    def _remove_duplicates(self, stocks: list[Stock]) -> list[Stock]:
        seen: set[str] = set()
        result: list[Stock] = []

        for stock in stocks:
            if stock.stock_id in seen:
                continue

            seen.add(stock.stock_id)
            result.append(stock)

        return result
