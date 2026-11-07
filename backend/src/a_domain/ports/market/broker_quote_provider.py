from collections.abc import Callable, Collection
from typing import Protocol

from a_domain.model.market.ohlcv import Ohlcv
from a_domain.ports.market.price_provider import IRealtimeQuoteProvider


class IBrokerQuoteProvider[Snapshot](IRealtimeQuoteProvider, Protocol):
    """
    Realtime quotes from the broker's market data, read over the one broker login a process holds. The
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
