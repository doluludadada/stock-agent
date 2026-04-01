import asyncio
from datetime import datetime, timedelta

from sqlmodel import col, select

from a_domain.model.market.ohlcv import Ohlcv
from a_domain.model.market.stock import Stock
from a_domain.ports.market.price_provider import IPriceProvider
from a_domain.ports.system.logging_provider import ILoggingProvider
from c_infrastructure.database.db_connector import DatabaseConnector
from c_infrastructure.database.models.ohlcv_dto import OhlcvDTO


class CachedPriceProvider(IPriceProvider):
    def __init__(self, fallback_provider: IPriceProvider, db: DatabaseConnector, logger: ILoggingProvider):
        self._fallback = fallback_provider
        self._db = db
        self._logger = logger
        # Throttle DB connections to prevent SQLite pool exhaustion
        self._db_semaphore = asyncio.Semaphore(20)

    async def fetch_realtime_bars(self, stocks: list[Stock]) -> dict[str, Ohlcv]:
        return await self._fallback.fetch_realtime_bars(stocks)

    async def fetch_history(self, stocks: list[Stock], start_date: datetime, end_date: datetime) -> dict[str, list[Ohlcv]]:
        result_map = {}

        async def _process(stock: Stock):
            async with self._db_semaphore:
                # 1. Check DB (Using col() to satisfy Pylance strict typing)
                async with self._db.get_session() as session:
                    stmt = select(OhlcvDTO).where(OhlcvDTO.stock_id == stock.stock_id).order_by(col(OhlcvDTO.ts))
                    result = await session.execute(stmt)
                    db_records = list(result.scalars().all())

                latest_ts = db_records[-1].ts if db_records else None

                # 2. Fetch missing delta if necessary
                if not latest_ts or latest_ts.date() < end_date.date():
                    fetch_start = latest_ts + timedelta(days=1) if latest_ts else start_date

                    if fetch_start.date() <= end_date.date():
                        # Pass a list of 1 stock to the fallback provider
                        new_data_map = await self._fallback.fetch_history([stock], fetch_start, end_date)
                        new_data = new_data_map.get(stock.stock_id, [])

                        if new_data:
                            # 3. Save new data to DB (one session per stock, add_all for atomicity)
                            try:
                                async with self._db.get_session() as session:
                                    for bar in new_data:
                                        dto = OhlcvDTO(
                                            stock_id=stock.stock_id,
                                            ts=bar.ts,
                                            open=bar.open,
                                            high=bar.high,
                                            low=bar.low,
                                            close=bar.close,
                                            volume=bar.volume,
                                            adj_close=bar.adj_close if bar.adj_close is not None else 0.0,
                                        )
                                        session.add(dto)
                                    await session.commit()
                            except Exception as e:
                                self._logger.warning(f"Cache write failed for {stock.stock_id}: {e}")

                            db_records = db_records + new_data

                # 4. Filter strictly to requested dates
                valid_bars = [r for r in db_records if start_date.date() <= r.ts.date() <= end_date.date()]
                return stock.stock_id, valid_bars

        # Process the caching concurrently
        results = await asyncio.gather(*[_process(s) for s in stocks])
        for sid, bars in results:
            if bars:
                result_map[sid] = bars

        return result_map
