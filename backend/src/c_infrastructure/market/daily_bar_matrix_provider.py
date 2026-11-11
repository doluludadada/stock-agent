import asyncio
from datetime import date
from typing import override

from a_domain.ports.market.daily_bar_matrix_provider import IDailyBarMatrixProvider
from a_domain.ports.market.price_provider import IOhlcvProvider
from a_domain.ports.market.stock_provider import IStockProvider
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.system.market_clock import IMarketClock
from a_domain.rules.technical.matrix import DailyBarMatrix
from a_domain.rules.trading.backtest import DailyBarMatrixRule


class DailyBarMatrixProvider(IDailyBarMatrixProvider):
    """
    The matrix of every listed stock's history from the price source, kept in this object for as long as the source
    holds the same first and last session. dependencies.py builds one per runtime, so new settings start from an empty
    one. One load builds at a time, and the callers that wait get its matrix. The bars become arrays in a worker thread.
    """

    def __init__(
        self, stock_provider: IStockProvider, ohlcv_provider: IOhlcvProvider, market_clock: IMarketClock, logger: ILoggingProvider
    ) -> None:
        self._stock_provider = stock_provider
        self._ohlcv_provider = ohlcv_provider
        self._clock = market_clock
        self._logger = logger
        self._matrix_rule = DailyBarMatrixRule()
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
