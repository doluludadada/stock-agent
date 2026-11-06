from collections.abc import Callable, Collection, Sequence
from datetime import date
from typing import Protocol

from a_domain.model.market.ohlcv import Ohlcv
from a_domain.ports.market.price_provider import IRealtimeQuoteProvider
from a_domain.types.enums import MarketType


class IBrokerQuoteProvider[Snapshot](IRealtimeQuoteProvider, Protocol):
    """
    Realtime and daily quotes from the broker's market data, read over the one broker login a process holds. The
    broker's orders share that login: the quote provider logs in, and the broker only checks the account on it.
    Snapshot is the SDK's record of one stock's session so far. A failed request or login raises saying only what
    failure_of says of the SDK's error.
    """

    async def connect(self) -> None:
        """
        Logs in to the broker unless the process's login is up: once per process, and again only after the login
        failed or the broker reported it down. Every later provider reads the same login.
        """
        ...

    async def snapshots(self, stock_ids: Collection[str]) -> list[Snapshot]:
        """The snapshot of each stock the broker has a contract for, in requests of at most market_data.quote_batch_size."""
        ...

    def quote_of(self, snapshot: Snapshot) -> Ohlcv | None:
        """
        The session so far, closing at the last trade and stamped with the exchange's time of that trade, with its change
        from the session's reference price. A stock that has not traded this session gets no quote: its price is the
        reference price, which nobody paid.
        """
        ...

    async def fetch_session_bars(self, session: date) -> dict[str, Ohlcv]:
        """
        Every listed stock's official daily bar of the session by stock id, stamped at the session's close, from one
        request. The broker gives no change with them. A stock that did not trade has no bar, and a date without a
        session, or whose bars the broker does not serve yet, has none at all.
        """
        ...

    async def fetch_session_changes(self, session: date, stock_ids: Collection[str]) -> dict[str, float]:
        """
        Each stock's change from its reference price in the session, from its snapshot while the snapshots still show
        that session: from its close until the next session opens. A stock whose snapshot shows another session has none.
        """
        ...

    async def fetch_index_bars(self, market: MarketType, first: date, last: date) -> list[Ohlcv]:
        """
        The exchange's own index (the TAIEX, the TPEx Index) per session from first to last, oldest first (daily_bars of
        its one-minute bars).
        """
        ...

    def daily_bars(self, minutes: Sequence[Ohlcv]) -> list[Ohlcv]:
        """
        The session bars of one-minute bars stamped in Taipei wall-clock time, oldest first: each opens at its first
        minute, closes at its last and is stamped at the session's close, with its change from the session before it.
        The first has no change: no session before it was asked.
        """
        ...

    async def request[**Arguments, Answer](
        self, interval_seconds: float, call: Callable[Arguments, Answer], *args: Arguments.args, **kwargs: Arguments.kwargs
    ) -> Answer:
        """
        Makes one request, `call` with its arguments in a worker thread, once interval_seconds have passed since the
        login's request before it of any kind, from any runtime. Its failure raises RuntimeError saying what failure_of
        says of the SDK's error.
        """
        ...

    def failure_of(self, error: Exception) -> str:
        """
        What logs and run records may say of an error of the broker's SDK: its type and the server's status. Never its
        text, which holds the server's whole answer, the login's person id and addresses included.
        """
        ...
