import asyncio
from dataclasses import asdict
from datetime import date, datetime, time, timedelta, tzinfo
from typing import override

from sqlmodel import col, select

from a_domain.model.market.ohlcv import Ohlcv
from a_domain.model.market.stock import Stock
from a_domain.ports.market.cached_price_provider import HistoryDownload, ICachedPriceProvider
from a_domain.ports.market.price_provider import IPriceHistoryProvider, IRealtimeQuoteProvider
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.system.market_clock import IMarketClock
from a_domain.types.enums import MarketIndex
from b_application.config.market_data_config import MarketDataConfig
from c_infrastructure.database.db_connector import DatabaseConnector
from c_infrastructure.database.models.ohlcv_dto import OhlcvDTO, OhlcvFetchDTO, OhlcvWindowDTO


class CachedPriceProvider(ICachedPriceProvider):
    """
    Daily history from the history source, cached in SQLite. Realtime quotes go to the quote source and are never cached.

    The cache keys each stock's bars by its stock_id and an index's by `^` and its MarketIndex value, which no stock_id
    can be.
    """

    def __init__(
        self,
        history_provider: IPriceHistoryProvider,
        quote_provider: IRealtimeQuoteProvider,
        db: DatabaseConnector,
        market_data: MarketDataConfig,
        logger: ILoggingProvider,
        market_clock: IMarketClock,
        write_lock: asyncio.Lock,
    ):
        self._history_provider = history_provider
        self._quote_provider = quote_provider
        self._db = db
        self._save_chunk_size = market_data.history_save_chunk_size
        self._retry_interval = timedelta(hours=market_data.history_retry_hours)
        self._start_slack = timedelta(days=market_data.history_start_slack_days)
        # Two requests that fetch the same new stock would both insert its rows; one at a time, the second updates them.
        # The lock is the process's, so a retired runtime still finishing a run writes one at a time with the new one.
        self._write_lock = write_lock
        self._downloads: dict[tuple[str, date, date], asyncio.Future[dict[str, list[Ohlcv]]]] = {}
        self._logger = logger
        self._clock = market_clock

    @override
    async def fetch_realtime_bars(self, stocks: list[Stock]) -> dict[str, Ohlcv]:
        return await self._quote_provider.fetch_realtime_bars(stocks)

    @override
    async def fetch_history(self, stocks: list[Stock], start_date: datetime, end_date: datetime) -> dict[str, list[Ohlcv]]:
        by_id = {stock.stock_id: stock for stock in stocks}

        async def download(due: list[str]) -> dict[str, list[Ohlcv]]:
            return await self._history_provider.fetch_history([by_id[stock_id] for stock_id in due], start_date, end_date)

        return await self.cached_history(list(by_id), start_date, end_date, download)

    @override
    async def fetch_index_history(self, index: MarketIndex, start_date: datetime, end_date: datetime) -> list[Ohlcv]:
        key = f"^{index.value}"

        async def download(due: list[str]) -> dict[str, list[Ohlcv]]:
            return {key: await self._history_provider.fetch_index_history(index, start_date, end_date)}

        return (await self.cached_history([key], start_date, end_date, download)).get(key, [])

    @override
    async def cached_history(
        self, stock_ids: list[str], start_date: datetime, end_date: datetime, download: HistoryDownload
    ) -> dict[str, list[Ohlcv]]:
        if not stock_ids:
            return {}

        now = self._clock.now()
        # Daily history holds settled sessions only. Yahoo also returns the session in progress, and a closed session's
        # bar keeps changing until it settles; caching either would freeze a provisional price as that day's close.
        first_session, last_session = self._clock.to_trading_date(start_date), self._clock.to_trading_date(end_date)
        last_settled_session = min(last_session, self._clock.last_settled_session())
        cached_bars = await self.load_cached_bars(stock_ids, first_session, last_session, now.tzinfo)
        cached, asked_from = self.settled_bars(cached_bars, last_settled_session), await self.load_windows(list(cached_bars))
        stale = await self.stocks_due(self.stocks_behind(stock_ids, cached, last_settled_session), last_settled_session, now)
        due = list(dict.fromkeys([*self.stocks_short_of(stock_ids, cached, asked_from, first_session), *stale]))

        if not due:
            self._logger.info(f"History cache hit: {len(stock_ids)} stocks")
            return cached

        self._logger.info(f"History cache miss: {len(due)}/{len(stock_ids)} stocks")
        fresh = self.settled_bars(await self.download_once(due, first_session, last_settled_session, download), last_settled_session)

        async with self._write_lock:
            await self.save_bars(fresh)
            # An index that came back empty is asked again at the next call: the overview has no other source for it.
            await self.save_fetches([key for key in due if key in fresh or not key.startswith("^")], now, last_settled_session)
            await self.save_windows([stock_id for stock_id in due if stock_id in fresh], first_session, asked_from)

        return cached | fresh

    @override
    async def download_once(
        self, stock_ids: list[str], first_session: date, last_session: date, download: HistoryDownload
    ) -> dict[str, list[Ohlcv]]:
        downloads = {
            stock_id: running
            for stock_id in stock_ids
            if (running := self._downloads.get((stock_id, first_session, last_session))) is not None
        }

        if new := [stock_id for stock_id in stock_ids if stock_id not in downloads]:
            started = asyncio.ensure_future(download(new))
            keys = [(stock_id, first_session, last_session) for stock_id in new]
            self._downloads |= dict.fromkeys(keys, started)
            started.add_done_callback(lambda _: [self._downloads.pop(key) for key in keys])
            downloads |= dict.fromkeys(new, started)

        # Shielded: a caller that stops leaves the download running for the others that wait on it.
        tasks = list(set(downloads.values()))
        answers = dict(zip(tasks, await asyncio.gather(*(asyncio.shield(task) for task in tasks)), strict=True))
        return {stock_id: answers[task][stock_id] for stock_id, task in downloads.items() if stock_id in answers[task]}

    @override
    def stocks_behind(self, stock_ids: list[str], cached: dict[str, list[Ohlcv]], last_settled_session: date) -> list[str]:
        return [
            stock_id
            for stock_id in stock_ids
            if stock_id not in cached or self._clock.to_trading_date(cached[stock_id][-1].ts) < last_settled_session
        ]

    @override
    def stocks_short_of(
        self, stock_ids: list[str], cached: dict[str, list[Ohlcv]], asked_from: dict[str, date], first_session: date
    ) -> list[str]:
        return [
            stock_id
            for stock_id in stock_ids
            if stock_id in cached
            and (asked_from.get(stock_id) or self._clock.to_trading_date(cached[stock_id][0].ts)) > first_session + self._start_slack
        ]

    @override
    async def load_windows(self, stock_ids: list[str]) -> dict[str, date]:
        async with self._db.get_session() as session:
            result = await session.execute(select(OhlcvWindowDTO).where(col(OhlcvWindowDTO.stock_id).in_(stock_ids)))
            return {row.stock_id: row.first_session for row in result.scalars().all()}

    @override
    async def save_windows(self, stock_ids: list[str], first_session: date, asked_from: dict[str, date]) -> None:
        earlier = [stock_id for stock_id in stock_ids if stock_id not in asked_from or first_session < asked_from[stock_id]]

        async with self._db.get_session() as session:
            for stock_id in earlier:
                await session.merge(OhlcvWindowDTO(stock_id=stock_id, first_session=first_session))

            await session.commit()

    @override
    async def stocks_due(self, behind: list[str], last_settled_session: date, now: datetime) -> list[str]:
        if not behind:
            return []

        async with self._db.get_session() as session:
            result = await session.execute(select(OhlcvFetchDTO).where(col(OhlcvFetchDTO.stock_id).in_(behind)))
            fetches = {fetch.stock_id: fetch for fetch in result.scalars().all()}

        # A history behind the last settled session is asked for once that session settled, then at most every
        # retry interval: Yahoo can leave a session without a close for hours, and asking on every call downloaded the
        # whole market again on every run.
        due = [
            stock_id
            for stock_id in behind
            if (fetch := fetches.get(stock_id)) is None
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
            bars_by_stock.setdefault(record.stock_id, []).append(Ohlcv(**record.model_dump(exclude={"stock_id"})))

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
                    await session.merge(OhlcvDTO(stock_id=stock_id, **asdict(bar)))
                    saved_count += 1

                    if saved_count % self._save_chunk_size == 0:
                        await session.commit()
                        self._logger.info(f"Saved OHLCV cache progress: {saved_count}/{total}")

            await session.commit()

        self._logger.info(f"Saved OHLCV cache completed: {saved_count}/{total}")

    @override
    async def save_fetches(self, stock_ids: list[str], fetched_at: datetime, settled_session: date) -> None:
        async with self._db.get_session() as session:
            for stock_id in stock_ids:
                await session.merge(OhlcvFetchDTO(stock_id=stock_id, fetched_at=fetched_at, settled_session=settled_session))

            await session.commit()

    @override
    def settled_bars(self, bars_by_stock: dict[str, list[Ohlcv]], last_settled_session: date) -> dict[str, list[Ohlcv]]:
        settled = {
            stock_id: [bar for bar in bars if self._clock.to_trading_date(bar.ts) <= last_settled_session]
            for stock_id, bars in bars_by_stock.items()
        }
        return {stock_id: bars for stock_id, bars in settled.items() if bars}
