import asyncio
from collections.abc import Hashable, Mapping
from dataclasses import dataclass, field
from datetime import date
from typing import override

from a_domain.ports.market.daily_bar_matrix_provider import IDailyBarMatrixProvider
from a_domain.ports.market.daily_close_archive import IDailyCloseArchive
from a_domain.ports.market.price_provider import IOhlcvProvider
from a_domain.ports.market.stock_provider import IStockProvider
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.system.market_clock import IMarketClock
from a_domain.rules.technical.matrix import DailyBarMatrix, DailyBarMatrixRule
from a_domain.rules.trading.ranking import RankingHistory, RankingHistoryRule
from a_domain.rules.trading.ranking_backtest import RankingBacktest, RankingBacktestRule


@dataclass
class KeptRankingHistory:
    """
    The ranking's history one process keeps, whichever settings it runs on, and the replays made of it. A settings
    save opens a new runtime, and reading millions of bars again for each would cost seconds and a second copy in
    memory, so every runtime's DailyBarMatrixProvider shares this one. `fingerprint` says what the history was built
    from, the rule that built it included; the replays are those of this history alone and go when it is built again.
    """

    building: asyncio.Lock = field(default_factory=asyncio.Lock)
    fingerprint: tuple[object, ...] | None = None
    history: RankingHistory | None = None
    backtests: dict[Hashable, RankingBacktest] = field(default_factory=dict)


class DailyBarMatrixProvider(IDailyBarMatrixProvider):
    """
    The matrix of every listed stock's history from the price source, kept in this object for as long as the source
    holds the same first and last session, and the ranking's history, kept in `kept`, which the process shares, for as
    long as the source's listed bars and references and the archive's revenue are the ones it was built from
    (listed_fingerprint, revenue_fingerprint), which a repeat load asks in two short statements. dependencies.py builds
    one per runtime, so new settings start from an empty matrix and from the ranking's history as it is. One load
    builds at a time, and the callers that wait get what it built. The matrix's bars become arrays, and the ranking's
    returns and its replays are worked out, in a worker thread. It keeps `kept_backtests` replays, the oldest leaving
    first.
    """

    def __init__(
        self,
        stock_provider: IStockProvider,
        ohlcv_provider: IOhlcvProvider,
        archive: IDailyCloseArchive,
        market_clock: IMarketClock,
        history_rule: RankingHistoryRule,
        logger: ILoggingProvider,
        kept: KeptRankingHistory,
        kept_backtests: int,
    ) -> None:
        self._stock_provider = stock_provider
        self._ohlcv_provider = ohlcv_provider
        self._archive = archive
        self._clock = market_clock
        self._logger = logger
        self._matrix_rule = DailyBarMatrixRule()
        self._history_rule = history_rule
        self._kept = kept
        self._kept_backtests = kept_backtests
        self._building = asyncio.Lock()
        self._held: tuple[date, date] | None = None
        self._matrix: DailyBarMatrix | None = None

    @override
    async def load(self) -> DailyBarMatrix | None:
        async with self._building:
            held = await self._ohlcv_provider.held_span()

            if held is None or held == self._held:
                return self._matrix if held else None

            stocks = await self._stock_provider.get_all()
            window = self._clock.session_close(held[0]), self._clock.session_close(held[1])
            history = await self._ohlcv_provider.fetch_history(stocks, *window)
            self._matrix = await asyncio.to_thread(self._matrix_rule.apply, history, self._clock.to_trading_date)
            self._held = held
            self._logger.info(f"Daily bar matrix: {len(self._matrix.stock_ids)} stocks x {len(self._matrix.sessions)} sessions")

            return self._matrix

    @override
    async def load_ranking_history(self) -> RankingHistory | None:
        """
        The fingerprint is read before the bars, so a bar saved while they are read shows as a change at the next load,
        and kept only with what was built from it, so a load that fails or is cancelled keeps nothing.
        """
        kept = self._kept

        async with kept.building:
            fingerprint = (
                self._history_rule,
                *await self._ohlcv_provider.listed_fingerprint(),
                *await self._archive.revenue_fingerprint(),
            )

            if fingerprint == kept.fingerprint:
                return kept.history

            listed = await self._ohlcv_provider.listed_history()
            history = None

            if listed is not None:
                revenues = await self._archive.revenue_history(date.min, listed.bars.sessions[-1])
                history = await asyncio.to_thread(self._history_rule.apply, listed, revenues)

            kept.history, kept.fingerprint, kept.backtests = history, fingerprint, {}

            return history

    @override
    async def ranking_backtest(
        self, history: RankingHistory, rule: RankingBacktestRule, names: Mapping[str, str | None], first: date, last: date
    ) -> RankingBacktest:
        key = (rule, frozenset(names.items()), first, last)

        if history is self._kept.history and key in self._kept.backtests:
            return self._kept.backtests[key]

        backtest = await asyncio.to_thread(rule.apply, history, names, first, last)
        backtests = self._kept.backtests

        if history is self._kept.history and self._kept_backtests:
            for oldest in list(backtests)[: max(0, len(backtests) + 1 - self._kept_backtests)]:
                del backtests[oldest]

            backtests[key] = backtest

        return backtest
