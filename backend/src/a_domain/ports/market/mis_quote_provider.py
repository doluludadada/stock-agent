from typing import Any, Protocol

from a_domain.model.market.ohlcv import Ohlcv
from a_domain.ports.market.price_provider import IRealtimeQuoteProvider


class IMisQuoteProvider(IRealtimeQuoteProvider, Protocol):
    """Realtime quotes from the TWSE market information system (MIS), and how its getStockInfo.jsp answers are read."""

    def parse_quotes(self, payload: dict[str, Any]) -> dict[str, Ohlcv]:
        """Each traded stock's quote in one getStockInfo.jsp response, by stock id. Raises when the API refused the request."""
        ...

    def parse_quote(self, item: dict[str, Any]) -> Ohlcv | None:
        """
        The session so far, closing at the last trade and stamped with that trade's time.

        z and t are the last trade. When the latest update was not a trade, z is "-" and t is the update's time, so the
        trade object's z and t are used instead, as the exchange's own quote page does. A stock that has not traded this
        session has neither and gets no quote: a bid or an ask is not a price anyone paid.
        """
        ...

    def parse_number(self, text: Any) -> float | None:
        """A number field of the response, or None when it holds no number (MIS writes "-")."""
        ...

    async def wait_for_request_slot(self) -> None:
        """Waits until the request interval has passed since the previous request, then claims the slot."""
        ...
