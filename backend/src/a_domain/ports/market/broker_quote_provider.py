from typing import Protocol

from a_domain.ports.market.price_provider import IRealtimeQuoteProvider


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
