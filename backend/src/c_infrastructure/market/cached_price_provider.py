# backend/src/c_infrastructure/market/cached_price_provider.py

from datetime import date, datetime, time, timedelta, tzinfo
from typing import override

from sqlmodel import col, select

from a_domain.model.market.ohlcv import Ohlcv
from a_domain.model.market.stock import Stock
from a_domain.ports.market.cached_price_provider import ICachedPriceProvider
from a_domain.ports.market.price_provider import IPriceHistoryProvider, IRealtimeQuoteProvider
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.system.market_clock import IMarketClock
from b_application.config.market_data_config import MarketDataConfig
from c_infrastructure.database.db_connector import DatabaseConnector
from c_infrastructure.database.models.ohlcv_dto import OhlcvDTO, OhlcvFetchDTO


class CachedPriceProvider(ICachedPriceProvider):
    """Daily history from the history source, cached in SQLite. Realtime quotes go to the quote source and are never cached."""

    def __init__(
        self,
        history_provider: IPriceHistoryProvider,
        quote_provider: IRealtimeQuoteProvider,
        db: DatabaseConnector,
        market_data: MarketDataConfig,
        logger: ILoggingProvider,
        market_clock: IMarketClock,
    ):
        self._history_provider = history_provider
        self._quote_provider = quote_provider
        self._db = db
        self._save_chunk_size = market_data.history_save_chunk_size
        self._retry_interval = timedelta(hours=market_data.history_retry_hours)
        self._logger = logger
        self._clock = market_clock

    @override
    async def fetch_realtime_bars(self, stocks: list[Stock]) -> dict[str, Ohlcv]:
        return await self._quote_provider.fetch_realtime_bars(stocks)

    @override
    async def fetch_history(self, stocks: list[Stock], start_date: datetime, end_date: datetime) -> dict[str, list[Ohlcv]]:
        stocks = list({stock.stock_id: stock for stock in stocks}.values())

        if not stocks:
            return {}

        now = self._clock.now()
        # Daily history holds settled sessions only. Yahoo also returns the session in progress, and a closed session's
        # bar keeps changing until it settles; caching either would freeze a provisional price as that day's close.
        last_settled_session = min(self._clock.to_trading_date(end_date), self._clock.last_settled_session())
        cached_bars = await self.load_cached_bars(
            [stock.stock_id for stock in stocks],
            self._clock.to_trading_date(start_date),
            self._clock.to_trading_date(end_date),
            now.tzinfo,
        )
        cached = self.settled_bars(cached_bars, last_settled_session)
        due = await self.stocks_due(self.stocks_behind(stocks, cached, last_settled_session), last_settled_session, now)

        if not due:
            self._logger.info(f"History cache hit: {len(stocks)} stocks")
            return cached

        self._logger.info(f"History cache miss: {len(due)}/{len(stocks)} stocks")
        fresh = self.settled_bars(await self._history_provider.fetch_history(due, start_date, end_date), last_settled_session)

        await self.save_bars(fresh)
        await self.save_fetches(due, now, last_settled_session)

        return cached | fresh

    @override
    def stocks_behind(self, stocks: list[Stock], cached: dict[str, list[Ohlcv]], last_settled_session: date) -> list[Stock]:
        return [
            stock
            for stock in stocks
            if stock.stock_id not in cached or self._clock.to_trading_date(cached[stock.stock_id][-1].ts) < last_settled_session
        ]

    @override
    async def stocks_due(self, behind: list[Stock], last_settled_session: date, now: datetime) -> list[Stock]:
        if not behind:
            return []

        async with self._db.get_session() as session:
            result = await session.execute(
                select(OhlcvFetchDTO).where(col(OhlcvFetchDTO.stock_id).in_([stock.stock_id for stock in behind]))
            )
            fetches = {fetch.stock_id: fetch for fetch in result.scalars().all()}

        # A history behind the last settled session is asked for once that session settled, then at most every
        # retry interval: Yahoo can leave a session without a close for hours, and asking on every call downloaded the
        # whole market again on every run.
        due = [
            stock
            for stock in behind
            if (fetch := fetches.get(stock.stock_id)) is None
            or fetch.settled_session < last_settled_session
            or now - fetch.fetched_at >= self._retry_interval
        ]

        if len(due) < len(behind):
            self._logger.info(
                f"History cache: {len(behind) - len(due)} stocks lack the {last_settled_session} session, "
                f"and the history source was asked for them less than {self._retry_interval} ago"
            )

        return due

    @override
    async def load_cached_bars(
        self, stock_ids: list[str], start_day: date, end_day: date, zone: tzinfo | None
    ) -> dict[str, list[Ohlcv]]:
        async with self._db.get_session() as session:
            stmt = (
                select(OhlcvDTO)
                .where(col(OhlcvDTO.stock_id).in_(stock_ids))
                .where(col(OhlcvDTO.ts) >= datetime.combine(start_day, time.min, tzinfo=zone))
                .where(col(OhlcvDTO.ts) <= datetime.combine(end_day, time.max, tzinfo=zone))
                .order_by(col(OhlcvDTO.stock_id), col(OhlcvDTO.ts))
            )

            result = await session.execute(stmt)
            records = result.scalars().all()

        bars_by_stock: dict[str, list[Ohlcv]] = {}

        for record in records:
            bars_by_stock.setdefault(record.stock_id, []).append(Ohlcv.model_validate(record))

        return bars_by_stock

    @override
    async def save_bars(self, bars_by_stock: dict[str, list[Ohlcv]]) -> None:
        total = sum(len(bars) for bars in bars_by_stock.values())

        if total == 0:
            return

        self._logger.info(f"Saving OHLCV cache: {total} bars")
        saved_count = 0

        async with self._db.get_session() as session:
            for stock_id, bars in bars_by_stock.items():
                for bar in bars:
                    await session.merge(OhlcvDTO(stock_id=stock_id, **bar.model_dump()))
                    saved_count += 1

                    if saved_count % self._save_chunk_size == 0:
                        await session.commit()
                        self._logger.info(f"Saved OHLCV cache progress: {saved_count}/{total}")

            await session.commit()

        self._logger.info(f"Saved OHLCV cache completed: {saved_count}/{total}")

    @override
    async def save_fetches(self, stocks: list[Stock], fetched_at: datetime, settled_session: date) -> None:
        async with self._db.get_session() as session:
            for stock in stocks:
                await session.merge(OhlcvFetchDTO(stock_id=stock.stock_id, fetched_at=fetched_at, settled_session=settled_session))

            await session.commit()

    @override
    def settled_bars(self, bars_by_stock: dict[str, list[Ohlcv]], last_settled_session: date) -> dict[str, list[Ohlcv]]:
        settled = {
            stock_id: [bar for bar in bars if self._clock.to_trading_date(bar.ts) <= last_settled_session]
            for stock_id, bars in bars_by_stock.items()
        }
        return {stock_id: bars for stock_id, bars in settled.items() if bars}
