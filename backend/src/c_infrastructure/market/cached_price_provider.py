import asyncio
from collections.abc import Mapping
from dataclasses import asdict, replace
from datetime import date, datetime, timedelta
from typing import override

import numpy as np
from sqlalchemy import Numeric, cast, func
from sqlmodel import col, select

from a_domain.model.market.ohlcv import Ohlcv
from a_domain.model.market.stock import Stock
from a_domain.ports.market.cached_price_provider import ICachedPriceProvider
from a_domain.ports.market.daily_close_archive import IDailyCloseArchive
from a_domain.ports.market.daily_history_source import IDailyHistorySource
from a_domain.ports.market.price_provider import IRealtimeQuoteProvider
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.system.market_clock import IMarketClock
from a_domain.rules.market.listing import HistoryAdjustmentRule
from a_domain.rules.technical.matrix import DailyBarMatrix
from a_domain.rules.trading.ranking import ListedHistory, ex_right_matrix
from a_domain.types.enums import MarketIndex, MarketType
from b_application.config.market_data_config import MarketDataConfig
from c_infrastructure.database.db_connector import UPSERT, DatabaseConnector
from c_infrastructure.database.models.ohlcv_dto import ExRightReferenceDTO, OhlcvDTO


class CachedPriceProvider(ICachedPriceProvider):
    """
    The history cache in ohlcv_data over the exchanges' daily reports. A sync takes one index range or one session at a
    time under the cache's lock, so a read that needs a few sessions waits for at most one session of a backfill that
    is running; the process's write lock orders the saves of every runtime's cache. A sync that a report fails stops
    there, and the read serves what the cache holds.
    """

    def __init__(
        self,
        quotes: IRealtimeQuoteProvider,
        source: IDailyHistorySource,
        archive: IDailyCloseArchive,
        db: DatabaseConnector,
        market_clock: IMarketClock,
        market_data: MarketDataConfig,
        reference_months: int,
        logger: ILoggingProvider,
        write_lock: asyncio.Lock,
    ) -> None:
        self._quotes = quotes
        self._reference_months = reference_months
        self._source = source
        self._archive = archive
        self._db = db
        self._clock = market_clock
        self._retry_interval = timedelta(hours=market_data.history_retry_hours)
        self._start_slack = timedelta(days=market_data.history_start_slack_days)
        self._logger = logger
        # A retired runtime still finishing a run and the current one write one at a time.
        self._write_lock = write_lock
        self._sync_lock = asyncio.Lock()
        self._asked: dict[str, datetime] = {}
        self._failed_at: datetime | None = None
        self._adjustment = HistoryAdjustmentRule()

    @override
    async def fetch_realtime_bars(self, stocks: list[Stock]) -> dict[str, Ohlcv]:
        return await self._quotes.fetch_realtime_bars(stocks)

    @override
    async def fetch_history(self, stocks: list[Stock], start_date: datetime, end_date: datetime) -> dict[str, list[Ohlcv]]:
        if not stocks:
            return {}

        first, last = await self.sync(start_date, end_date)
        stored = await self.stored_bars([stock.stock_id for stock in stocks], first, last)
        held = await self.held_sessions(first, last)
        indexes = {
            market: [bar for bar in bars if self._clock.to_trading_date(bar.ts) in held]
            for market, bars in (await self.index_sessions(first, last)).items()
        }
        listed = await self.ex_right_references(first, last)
        unadjustable = {
            bar.ts for key, bars in stored.items() for bar in bars[1:] if bar.change is None and bar.ts not in listed.get(key, {})
        }

        self._logger.info(f"Daily history from the exchanges' reports: {len(stored)}/{len(stocks)} stocks, {len(held)} sessions")
        if unadjustable:
            self._logger.warning(
                f"Daily history from {first} to {last}: {len(unadjustable)} sessions hold bars with no change from the exchanges "
                "or the open-data archive, so a split, a capital reduction or a dividend there shows as the gap it traded at"
            )

        return {
            stock.stock_id: self._adjustment.apply(
                stored[stock.stock_id], indexes.get(stock.market, []), stock.market, listed.get(stock.stock_id, {})
            )
            for stock in stocks
            if stock.stock_id in stored
        }

    @override
    async def fetch_index_history(self, index: MarketIndex, start_date: datetime, end_date: datetime) -> list[Ohlcv]:
        first, last = self.sessions_of(start_date, end_date)

        try:
            await self.sync_index(index.market, first, last)
        except Exception as error:
            self._failed_at = self._clock.now()
            self._logger.warning(f"The exchange's index bars failed ({type(error).__name__}: {error}); serving the cached ones")

        return (await self.index_sessions(first, last)).get(index.market, [])

    @override
    async def held_span(self) -> tuple[date, date] | None:
        span = select(func.min(col(OhlcvDTO.ts)), func.max(col(OhlcvDTO.ts))).where(col(OhlcvDTO.stock_id).not_like("^%"))

        async with self._db.get_session() as session:
            first, last = (await session.execute(span)).one()

        if first is None or last is None:
            return None

        return self._clock.to_trading_date(first), self._clock.to_trading_date(last)

    @override
    def sessions_of(self, start_date: datetime, end_date: datetime) -> tuple[date, date]:
        last = min(self._clock.to_trading_date(end_date), self._clock.last_settled_session())
        return self._clock.to_trading_date(start_date), last

    @override
    async def sync(self, start_date: datetime, end_date: datetime, *, reported: bool = False) -> tuple[date, date]:
        first, last = self.sessions_of(start_date, end_date)

        try:
            for market in MarketType:
                await self.sync_index(market, first, last)

            await self.sync_references(first, last)
            index = await self.index_sessions(first, last)
            sessions = {self._clock.to_trading_date(bar.ts) for bars in index.values() for bar in bars}
            missing = sorted(sessions - await self.held_sessions(first, last, reported=reported), reverse=True)
            saved = [session for session in missing if await self.sync_session(session)]
        except Exception as error:
            self._failed_at = self._clock.now()
            self._logger.warning(
                f"The exchanges' daily history failed ({type(error).__name__}: {error}); reading what the cache holds"
            )
            return first, last

        if missing:
            self._logger.info(f"Daily history: {len(saved)}/{len(missing)} sessions the cache lacked saved from the exchanges")

        return first, last

    @override
    async def sync_index(self, market: MarketType, first: date, last: date) -> None:
        async with self._sync_lock:
            for start, end in await self.index_gaps(market, first, last):
                question = f"index {market.value} from {start} to {end}"

                if not self.due(question, self._clock.now()):
                    continue

                self._asked[question] = self._clock.now()
                bars = await self._source.index_bars(market, start, end)

                async with self._write_lock:
                    await self.save_bars({f"^{market.value}": bars})

    @override
    async def index_gaps(self, market: MarketType, first: date, last: date) -> list[tuple[date, date]]:
        """Each range runs from or to a session the cache holds, so that session's answer gives the next its change."""
        span = select(func.min(col(OhlcvDTO.ts)), func.max(col(OhlcvDTO.ts))).where(col(OhlcvDTO.stock_id) == f"^{market.value}")

        async with self._db.get_session() as session:
            earliest, latest = (await session.execute(span)).one()

        if earliest is None or latest is None:
            return [(first, last)] if first <= last else []

        earliest, latest = self._clock.to_trading_date(earliest), self._clock.to_trading_date(latest)
        before = [(first, earliest)] if first + self._start_slack < earliest else []
        return before + ([(latest, last)] if latest < last else [])

    @override
    async def sync_references(self, first: date, last: date) -> None:
        async with self._sync_lock:
            for start, end in await self.reference_gaps(first, last):
                question = f"ex-right references from {start} to {end}"

                if not self.due(question, self._clock.now()):
                    continue

                self._asked[question] = self._clock.now()

                try:
                    references = await self._source.ex_right_references(start, end)
                except Exception as error:
                    self._failed_at = self._clock.now()
                    self._logger.warning(f"TWSE's ex-right references from {start} failed ({type(error).__name__}: {error})")
                    return

                async with self._write_lock:
                    await self.save_references(references)

    @override
    async def save_references(self, references: Mapping[tuple[str, date], float]) -> None:
        """One upsert."""
        rows = [{"stock_id": stock_id, "session_date": day, "reference_price": price} for (stock_id, day), price in references.items()]

        if not rows:
            return

        async with self._db.get_session() as session:
            statement = UPSERT[session.get_bind().dialect.name](ExRightReferenceDTO)
            replaced = {"reference_price": statement.excluded["reference_price"]}
            await session.execute(statement.on_conflict_do_update(index_elements=["stock_id", "session_date"], set_=replaced), rows)
            await session.commit()

    @override
    async def reference_gaps(self, first: date, last: date) -> list[tuple[date, date]]:
        span = select(func.min(col(ExRightReferenceDTO.session_date)), func.max(col(ExRightReferenceDTO.session_date)))

        async with self._db.get_session() as session:
            earliest, latest = (await session.execute(span)).one()

        if earliest is None or latest is None:
            gaps = [(first, last)]
        else:
            gaps = ([(first, earliest)] if first + self._start_slack < earliest else []) + ([(latest, last)] if latest < last else [])

        cuts: list[tuple[date, date]] = []

        for start, end in gaps:
            while start <= end:
                block_end = (
                    start.year * 12 + start.month - 1
                ) // self._reference_months * self._reference_months + self._reference_months
                boundary = date(block_end // 12, block_end % 12 + 1, 1)
                cuts.append((start, min(end, boundary - timedelta(days=1))))
                start = boundary

        return cuts

    @override
    async def listed_history(self) -> ListedHistory | None:
        """
        Read as plain values on the session's connection, one session a statement, each straight into the matrices: the
        table's rows, or one object a bar, take minutes and gigabytes over millions of bars, and one statement over them
        all would hold SQLite's read lock, which no save gets past, for as long as it runs. The stocks and the stamps are
        those held when the read begins: a bar of another stock saved meanwhile goes to a spare row that is dropped.
        """
        stocks = col(OhlcvDTO.stock_id).not_like("^%")
        figures = (OhlcvDTO.open, OhlcvDTO.high, OhlcvDTO.low, OhlcvDTO.close, OhlcvDTO.volume, OhlcvDTO.change)
        listed = select(col(OhlcvDTO.stock_id), *map(col, figures)).where(stocks)

        async with self._db.get_session() as session:
            connection = await session.connection()
            stock_ids = tuple(sorted((await connection.execute(select(col(OhlcvDTO.stock_id)).distinct().where(stocks))).scalars()))
            stamps = sorted((await connection.execute(select(col(OhlcvDTO.ts)).distinct().where(stocks))).scalars())
            sessions = tuple(sorted({self._clock.to_trading_date(stamp) for stamp in stamps}))
            rows = {stock_id: row for row, stock_id in enumerate(stock_ids)}
            columns = {stamp: sessions.index(self._clock.to_trading_date(stamp)) for stamp in stamps}
            fields = [np.full((len(stock_ids) + 1, len(sessions)), np.nan) for _ in figures]

            for stamp, column in columns.items():
                part_stocks, *part_values = zip(*await connection.execute(listed.where(col(OhlcvDTO.ts) == stamp)), strict=True)
                cell = [rows.get(stock_id, len(rows)) for stock_id in part_stocks]

                for field, values in zip(fields, part_values, strict=True):
                    field[cell, column] = values

        if not stamps:
            return None

        open_price, high, low, close, volume, change = (field[:-1] for field in fields)
        references = await self.ex_right_references(sessions[0], sessions[-1])
        bars = DailyBarMatrix(stock_ids=stock_ids, sessions=sessions, open=open_price, high=high, low=low, close=close, volume=volume)
        return ListedHistory(bars=bars, change=change, ex_right_reference=ex_right_matrix(references, rows, columns, close))

    @override
    async def listed_fingerprint(self) -> tuple[object, ...]:
        """Each sum adds exact numerics, so the order a database adds the bars in cannot move it."""
        exact = Numeric(asdecimal=False)
        figures = (OhlcvDTO.open, OhlcvDTO.high, OhlcvDTO.low, OhlcvDTO.close, OhlcvDTO.volume, OhlcvDTO.change)
        sums = [func.sum(cast(col(figure), exact)) for figure in figures]
        bars = select(func.count(), func.count(col(OhlcvDTO.change)), *sums).where(col(OhlcvDTO.stock_id).not_like("^%"))
        references = select(func.count(), func.sum(cast(col(ExRightReferenceDTO.reference_price), exact)))

        async with self._db.get_session() as session:
            return (*(await session.execute(bars)).one(), *(await session.execute(references)).one())

    @override
    async def ex_right_references(self, first: date, last: date) -> dict[str, dict[datetime, float]]:
        statement = select(ExRightReferenceDTO).where(col(ExRightReferenceDTO.session_date).between(first, last))

        async with self._db.get_session() as session:
            rows = (await session.execute(statement)).scalars().all()

        references: dict[str, dict[datetime, float]] = {}

        for row in rows:
            references.setdefault(row.stock_id, {})[self._clock.session_close(row.session_date)] = row.reference_price

        return references

    @override
    async def sync_session(self, session: date) -> bool:
        question = f"daily reports of {session}"

        async with self._sync_lock:
            if session in await self.held_sessions(session, session, reported=True) or not self.due(question, self._clock.now()):
                return False

            self._asked[question] = self._clock.now()
            bars = await self._source.session_bars(session)

            async with self._write_lock:
                await self.save_bars({stock_id: [bar] for stock_id, bar in bars.items()})

        return bool(bars)

    @override
    def due(self, question: str, now: datetime) -> bool:
        return all(asked is None or now - asked >= self._retry_interval for asked in (self._asked.get(question), self._failed_at))

    @override
    async def held_sessions(self, first: date, last: date, *, reported: bool = False) -> set[date]:
        stamps = (
            select(col(OhlcvDTO.ts))
            .distinct()
            .where(col(OhlcvDTO.ts).between(self._clock.session_close(first), self._clock.session_close(last)))
            .where(col(OhlcvDTO.stock_id).not_like("^%"))
        )

        if reported:
            stamps = stamps.where(col(OhlcvDTO.change).is_not(None))

        async with self._db.get_session() as session:
            return {self._clock.to_trading_date(stamp) for stamp in (await session.execute(stamps)).scalars()}

    @override
    async def index_sessions(self, first: date, last: date) -> dict[MarketType, list[Ohlcv]]:
        keys = {f"^{market.value}": market for market in MarketType}
        statement = (
            select(OhlcvDTO)
            .where(col(OhlcvDTO.stock_id).in_(keys))
            .where(col(OhlcvDTO.ts).between(self._clock.session_close(first), self._clock.session_close(last)))
            .order_by(col(OhlcvDTO.ts))
        )

        async with self._db.get_session() as session:
            rows = (await session.execute(statement)).scalars().all()

        indexes: dict[MarketType, list[Ohlcv]] = {}

        for row in rows:
            indexes.setdefault(keys[row.stock_id], []).append(Ohlcv(**row.model_dump(exclude={"stock_id"})))

        return indexes

    @override
    async def stored_bars(self, stock_ids: list[str], first: date, last: date) -> dict[str, list[Ohlcv]]:
        statement = (
            select(OhlcvDTO)
            .where(col(OhlcvDTO.stock_id).in_(stock_ids))
            .where(col(OhlcvDTO.ts).between(self._clock.session_close(first), self._clock.session_close(last)))
            .order_by(col(OhlcvDTO.stock_id), col(OhlcvDTO.ts))
        )

        async with self._db.get_session() as session:
            rows = (await session.execute(statement)).scalars().all()

        lacking = sorted({row.stock_id for row in rows if row.change is None})
        official = await self._archive.official_changes(lacking, first, last) if lacking else {}
        bars: dict[str, list[Ohlcv]] = {}

        for row in rows:
            bar = Ohlcv(**row.model_dump(exclude={"stock_id"}))
            change = official.get((row.stock_id, self._clock.to_trading_date(bar.ts))) if bar.change is None else bar.change
            bars.setdefault(row.stock_id, []).append(replace(bar, change=change))

        return bars

    @override
    async def save_bars(self, bars: Mapping[str, list[Ohlcv]]) -> None:
        """One upsert. A bar saved without a change keeps the change the cache holds of it."""
        rows = [OhlcvDTO(stock_id=key, **asdict(bar)).model_dump() for key, key_bars in bars.items() for bar in key_bars]

        if not rows:
            return

        async with self._db.get_session() as session:
            statement = UPSERT[session.get_bind().dialect.name](OhlcvDTO)
            prices = {name: statement.excluded[name] for name in ("open", "high", "low", "close", "volume")}
            change = func.coalesce(statement.excluded["change"], statement.table.c.change)
            await session.execute(
                statement.on_conflict_do_update(index_elements=["stock_id", "ts"], set_=prices | {"change": change}), rows
            )
            await session.commit()
