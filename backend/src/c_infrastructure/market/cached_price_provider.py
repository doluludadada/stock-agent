# backend/src/c_infrastructure/market/cached_price_provider.py

from datetime import date, datetime

from sqlmodel import col, select

from a_domain.model.market.ohlcv import Ohlcv
from a_domain.model.market.stock import Stock
from a_domain.ports.market.price_provider import IOhlcvProvider
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.system.market_clock import IMarketClock
from c_infrastructure.database.db_connector import DatabaseConnector
from c_infrastructure.database.models.ohlcv_dto import OhlcvDTO


class CachedPriceProvider(IOhlcvProvider):
    SAVE_CHUNK_SIZE = 5_000

    def __init__(
        self,
        price_provider: IOhlcvProvider,
        db: DatabaseConnector,
        logger: ILoggingProvider,
        market_clock: IMarketClock,
    ):
        self._price_provider = price_provider
        self._db = db
        self._logger = logger
        self._clock = market_clock

    async def fetch_realtime_bars(self, stocks: list[Stock]) -> dict[str, Ohlcv]:
        return await self._price_provider.fetch_realtime_bars(stocks)

    async def fetch_history(
        self,
        stocks: list[Stock],
        start_date: datetime,
        end_date: datetime,
    ) -> dict[str, list[Ohlcv]]:
        stocks = self._remove_duplicate_stocks(stocks)

        if not stocks:
            return {}

        start_day = self._clock.to_trading_date(start_date)
        end_day = self._clock.to_trading_date(end_date)
        stock_ids = [stock.stock_id for stock in stocks]

        cached = await self._load_cached_bars(
            stock_ids=stock_ids,
            start_day=start_day,
            end_day=end_day,
        )

        missing = [stock for stock in stocks if stock.stock_id not in cached]

        if not missing:
            self._logger.info(f"History cache hit: {len(stocks)}/{len(stocks)} stocks")
            return cached

        self._logger.info(f"History cache miss: {len(missing)}/{len(stocks)} stocks")

        fresh = await self._price_provider.fetch_history(
            missing,
            start_date,
            end_date,
        )

        await self._save_bars(fresh)

        for stock_id, bars in fresh.items():
            cached[stock_id] = bars

        return self._clean_result(cached)

    async def _load_cached_bars(
        self,
        stock_ids: list[str],
        start_day: date,
        end_day: date,
    ) -> dict[str, list[Ohlcv]]:
        async with self._db.get_session() as session:
            stmt = (
                select(OhlcvDTO)
                .where(col(OhlcvDTO.stock_id).in_(stock_ids))
                .where(col(OhlcvDTO.trading_date) >= start_day)
                .where(col(OhlcvDTO.trading_date) <= end_day)
                .order_by(col(OhlcvDTO.stock_id), col(OhlcvDTO.trading_date))
            )

            result = await session.execute(stmt)
            records = result.scalars().all()

        bars_by_stock: dict[str, list[Ohlcv]] = {}

        for record in records:
            bars_by_stock.setdefault(record.stock_id, []).append(Ohlcv.model_validate(record))

        return bars_by_stock

    async def _save_bars(self, bars_by_stock: dict[str, list[Ohlcv]]) -> None:
        total = sum(len(bars) for bars in bars_by_stock.values())

        if total == 0:
            return

        self._logger.info(f"Saving OHLCV cache: {total} bars")

        saved_count = 0

        async with self._db.get_session() as session:
            for stock_id, bars in bars_by_stock.items():
                for bar in bars:
                    dto = OhlcvDTO(
                        stock_id=stock_id,
                        trading_date=self._clock.to_trading_date(bar.ts),
                        ts=bar.ts,
                        open=bar.open,
                        high=bar.high,
                        low=bar.low,
                        close=bar.close,
                        volume=bar.volume,
                        adj_close=bar.adj_close,
                    )

                    await session.merge(dto)
                    saved_count += 1

                    if saved_count % self.SAVE_CHUNK_SIZE == 0:
                        await session.commit()
                        self._logger.info(f"Saved OHLCV cache progress: {saved_count}/{total}")

            await session.commit()

        self._logger.info(f"Saved OHLCV cache completed: {saved_count}/{total}")

    def _clean_result(self, bars_by_stock: dict[str, list[Ohlcv]]) -> dict[str, list[Ohlcv]]:
        result: dict[str, list[Ohlcv]] = {}

        for stock_id, bars in bars_by_stock.items():
            unique_bars: dict[date, Ohlcv] = {}

            for bar in bars:
                unique_bars[self._clock.to_trading_date(bar.ts)] = bar

            sorted_bars = sorted(
                unique_bars.values(),
                key=lambda bar: self._clock.to_trading_date(bar.ts),
            )

            if sorted_bars:
                result[stock_id] = sorted_bars

        return result

    def _remove_duplicate_stocks(self, stocks: list[Stock]) -> list[Stock]:
        seen: set[str] = set()
        result: list[Stock] = []

        for stock in stocks:
            if stock.stock_id in seen:
                continue

            seen.add(stock.stock_id)
            result.append(stock)

        return result
