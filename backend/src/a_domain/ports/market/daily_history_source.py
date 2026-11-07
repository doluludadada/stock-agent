from collections.abc import Collection
from datetime import date
from typing import Any, Protocol

from a_domain.model.market.ohlcv import Ohlcv
from a_domain.types.enums import MarketType


class IDailyHistorySource(Protocol):
    """
    The exchanges' own reports of each date, which a personal site reads its daily history from without a login: every
    listed stock's official bar of one session, with its change from the session's reference price, and each
    exchange's own index (the TAIEX, the TPEx Index) per session. A failed request raises.
    """

    async def session_bars(self, session: date) -> dict[str, Ohlcv]:
        """
        Every listed stock's bar of the session by stock id, stamped at the session's close, from both exchanges or
        from neither: a date without a session, or one that either exchange does not serve yet, has none at all. A stock
        that did not trade has no bar, and one whose exchange compared its close to no reference, as on an ex-dividend
        day, has no change.
        """
        ...

    async def index_bars(self, market: MarketType, first: date, last: date) -> list[Ohlcv]:
        """The market's own index per session from first to last, oldest first, each with its official change."""
        ...

    async def get(self, market: MarketType, url: str) -> Any:
        """One report of the market's exchange as served, once the request interval has passed since its request before it."""
        ...

    def rows(self, answer: Any, fields: Collection[str]) -> list[dict[str, str]]:
        """
        Each row of the answer's first table that names every one of fields, by field name, its values as text. Names and
        values are read with the spaces around them removed. An answer with no such table raises: the report changed.
        """
        ...

    def quotes(self, answer: Any, market: MarketType, session: date) -> dict[str, Ohlcv]:
        """The bar of each stock with a four-digit code that traded, from one exchange's closing quotes of the session."""
        ...

    def change(self, sign: str, text: str, close: float) -> float | None:
        """The signed change a quote writes, or None where it compared the close to no reference (the listing's parse_change)."""
        ...

    def index_month(self, prices: Any, volumes: Any, market: MarketType) -> list[Ohlcv]:
        """
        The index's bar of each session of one month that both reports list: its prices from one, its market's volume in
        shares and its change from the other.
        """
        ...

    def session_date(self, text: str) -> date | None:
        """'114/07/01' (ROC year 114) and '2025/07/01' are both 2025-07-01; a row that writes no date has None."""
        ...
