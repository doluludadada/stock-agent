from collections.abc import Sequence
from datetime import date
from typing import Protocol

from a_domain.model.market.article import Article


class IArticleIndex(Protocol):
    """
    Finds a stock's kept articles by meaning: one vector per article of the article store (IArticleStore), under the
    article's stock and key, with the day it was published. It holds no article: a search answers keys, and the
    store answers the articles. Everything in it can be computed again from the store, so losing it loses nothing.
    """

    async def sync(self, stock_id: str, articles: Sequence[Article]) -> int:
        """
        Brings the stock's vectors in line with `articles`, the stock's kept articles, and says how many it embedded:
        an article with no vector of its current text gets one, a vector whose article is not among them is removed,
        and an article whose vector is of its current text is not embedded again.
        """
        ...

    async def search(self, stock_id: str, query: str, first: date | None, last: date | None, limit: int) -> list[str]:
        """
        The keys of the stock's indexed articles published from the day `first` on and before the day `last`, days of
        the exchange's calendar and None for no bound, whose text is closest in meaning to `query`: at most limit, the
        closest first.
        """
        ...

    def embedded_text(self, article: Article) -> str:
        """What of an article its vector stands for: its title, then the text kept with it, cut to the length the index reads."""
        ...
