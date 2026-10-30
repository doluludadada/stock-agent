# backend/src/c_infrastructure/market/cached_price_provider.py

from datetime import date, datetime, time, timedelta

from sqlmodel import col, select

from a_domain.model.market.ohlcv import Ohlcv
from a_domain.model.market.stock import Stock
from a_domain.ports.market.price_provider import IOhlcvProvider, IPriceHistoryProvider, IRealtimeQuoteProvider
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.system.market_clock import IMarketClock
from c_infrastructure.database.db_connector import DatabaseConnector
from c_infrastructure.database.models.ohlcv_dto import OhlcvDTO, OhlcvFetchDTO


class CachedPriceProvider(IOhlcvProvider):
    """Daily history from the history source, cached in SQLite. Realtime quotes go to the quote source and are never cached."""

    SAVE_CHUNK_SIZE = 5_000
    RETRY_INTERVAL = timedelta(hours=2)

    def __init__(
        self,
        history_provider: IPriceHistoryProvider,
        quote_provider: IRealtimeQuoteProvider,
        db: DatabaseConnector,
        logger: ILoggingProvider,
        market_clock: IMarketClock,
    ):
        self._history_provider = history_provider
        self._quote_provider = quote_provider
        self._db = db
        self._logger = logger
        self._clock = market_clock

    async def fetch_realtime_bars(self, stocks: list[Stock]) -> dict[str, Ohlcv]:
        return await self._quote_provider.fetch_realtime_bars(stocks)

    async def fetch_history(self, stocks: list[Stock], start_date: datetime, end_date: datetime) -> dict[str, list[Ohlcv]]:
        stocks = self._remove_duplicate_stocks(stocks)

        if not stocks:
            return {}

        start_day = self._clock.to_trading_date(start_date)
        end_day = self._clock.to_trading_date(end_date)
        stock_ids = [stock.stock_id for stock in stocks]
        now = self._clock.now()

        # Daily history holds settled sessions only. Yahoo also returns the session in progress, and a closed session's
        # bar keeps changing until it settles; caching either would freeze a provisional price as that day's close.
        last_settled_session = min(end_day, self._clock.last_settled_session())
        cached = self._settled_sessions(
            await self._load_cached_bars(stock_ids=stock_ids, start_day=start_day, end_day=end_day), last_settled_session
        )
        behind = [
            stock
            for stock in stocks
            if stock.stock_id not in cached or self._clock.to_trading_date(cached[stock.stock_id][-1].ts) < last_settled_session
        ]

        # A history behind the last settled session is asked for once that session settled, then at most every
        # RETRY_INTERVAL: Yahoo can leave a session without a close for hours, and asking on every call downloaded the
        # whole market again on every run.
        fetches = await self._load_fetches([stock.stock_id for stock in behind])
        due = [
            stock
            for stock in behind
            if (fetch := fetches.get(stock.stock_id)) is None
            or fetch.settled_session < last_settled_session
            or now - self._clock.to_market_datetime(fetch.fetched_at) >= self.RETRY_INTERVAL
        ]

        if len(due) < len(behind):
            self._logger.info(
                f"History cache: {len(behind) - len(due)} stocks lack the {last_settled_session} session, "
                f"and the history source was asked for them less than {self.RETRY_INTERVAL} ago"
            )

        if not due:
            self._logger.info(f"History cache hit: {len(stocks)} stocks")
            return cached

        self._logger.info(f"History cache miss: {len(due)}/{len(stocks)} stocks")

        fresh = self._settled_sessions(await self._history_provider.fetch_history(due, start_date, end_date), last_settled_session)

        await self._save_bars(fresh)
        await self._save_fetches(due, now, last_settled_session)

        return cached | fresh

    async def _load_cached_bars(self, stock_ids: list[str], start_day: date, end_day: date) -> dict[str, list[Ohlcv]]:
        async with self._db.get_session() as session:
            stmt = (
                select(OhlcvDTO)
                .where(col(OhlcvDTO.stock_id).in_(stock_ids))
                .where(col(OhlcvDTO.ts) >= datetime.combine(start_day, time.min))
                .where(col(OhlcvDTO.ts) <= datetime.combine(end_day, time.max))
                .order_by(col(OhlcvDTO.stock_id), col(OhlcvDTO.ts))
            )

            result = await session.execute(stmt)
            records = result.scalars().all()

        bars_by_stock: dict[str, list[Ohlcv]] = {}

        for record in records:
            bar = Ohlcv.model_validate(record)
            bar.ts = self._clock.to_market_datetime(bar.ts)
            bars_by_stock.setdefault(record.stock_id, []).append(bar)

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

    async def _load_fetches(self, stock_ids: list[str]) -> dict[str, OhlcvFetchDTO]:
        if not stock_ids:
            return {}

        async with self._db.get_session() as session:
            result = await session.execute(select(OhlcvFetchDTO).where(col(OhlcvFetchDTO.stock_id).in_(stock_ids)))
            return {fetch.stock_id: fetch for fetch in result.scalars().all()}

    async def _save_fetches(self, stocks: list[Stock], fetched_at: datetime, settled_session: date) -> None:
        async with self._db.get_session() as session:
            for stock in stocks:
                await session.merge(OhlcvFetchDTO(stock_id=stock.stock_id, fetched_at=fetched_at, settled_session=settled_session))

            await session.commit()

    def _settled_sessions(self, bars_by_stock: dict[str, list[Ohlcv]], last_settled_session: date) -> dict[str, list[Ohlcv]]:
        settled = {
            stock_id: [bar for bar in bars if self._clock.to_trading_date(bar.ts) <= last_settled_session]
            for stock_id, bars in bars_by_stock.items()
        }
        return {stock_id: bars for stock_id, bars in settled.items() if bars}

    def _remove_duplicate_stocks(self, stocks: list[Stock]) -> list[Stock]:
        seen: set[str] = set()
        result: list[Stock] = []

        for stock in stocks:
            if stock.stock_id in seen:
                continue

            seen.add(stock.stock_id)
            result.append(stock)

        return result
