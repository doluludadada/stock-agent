from collections.abc import Collection
from typing import Protocol

from a_domain.model.market.ohlcv import Ohlcv
from a_domain.ports.market.price_provider import IRealtimeQuoteProvider
from a_domain.types.enums import MarketIndex


class IBrokerQuoteProvider(IRealtimeQuoteProvider, Protocol):
    """
    Realtime quotes from the broker's market data, read over the one broker login a process holds. The
    broker's orders share that login: the quote provider logs in, and the broker only checks the account on it.
    A failed request or login raises saying only the type of the SDK's error and the server's status.
    """

    async def connect(self) -> None:
        """
        Logs in to the broker unless the process's login is up: once per process, and again only after the login
        failed or the broker reported it down. Every later provider reads the same login.
        """
        ...

    async def fetch_index_quotes(self, indexes: Collection[MarketIndex]) -> dict[MarketIndex, Ohlcv]:
        """
        Each market index's session so far, in one request of its own: closing at its latest value and stamped with
        that value's time, with its change from the previous close and no volume. An index the broker has no value or
        no contract of gets no bar. It asks nothing for no index.
        """
        ...
