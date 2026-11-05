from collections.abc import Mapping, Sequence
from typing import Annotated

from pydantic import Field
from pydantic.dataclasses import dataclass

from a_domain.model.market.ohlcv import Ohlcv
from a_domain.model.market.stock import Stock


@dataclass(frozen=True)
class StockSearchRule:
    """
    The listed stocks that match what a user typed, best first: the exact code, then codes that start with it, then
    names that contain it, each group in listing order. Case and surrounding spaces do not matter.
    """

    limit: Annotated[int, Field(gt=0)]

    def apply(self, stocks: Sequence[Stock], query: str) -> list[Stock]:
        text = query.strip().casefold()

        if not text:
            return []

        exact = [stock for stock in stocks if stock.stock_id.casefold() == text]
        prefix = [stock for stock in stocks if stock.stock_id.casefold().startswith(text) and stock.stock_id.casefold() != text]
        named = [stock for stock in stocks if text in (stock.name or "").casefold() and not stock.stock_id.casefold().startswith(text)]

        return [*exact, *prefix, *named][: self.limit]


@dataclass(frozen=True)
class MostTradedRule:
    """The stocks with the most shares traded in the listing's latest session, most first."""

    limit: Annotated[int, Field(gt=0)]

    def apply(self, closes: Mapping[str, Ohlcv]) -> list[str]:
        ranked = sorted(closes.items(), key=lambda item: item[1].volume, reverse=True)
        return [stock_id for stock_id, _ in ranked[: self.limit]]
