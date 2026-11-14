from collections.abc import Collection, Sequence
from typing import Protocol

from a_domain.model.market.article import Article


class IArticleStore(Protocol):
    """
    What the site read about each stock, kept so that it accumulates: every announcement, exchange news item, news
    article and board post once per stock under its key (Article.key), shared by every user and kept across restarts.
    It is the durable copy: the vectors that find an article by meaning (IArticleIndex) are rebuilt from it. It keeps
    what it is given, so the caller decides which text an article is kept with (KeptArticleRule). Retention bounds it:
    an article published longer ago than the retention window is dropped, and so is a stock's oldest beyond the most
    one stock may keep, which a document of record such as an annual report's section does not count toward.
    """

    async def save(self, articles: Sequence[Article]) -> int:
        """
        Keeps each article under its stock and key, and says how many it added or replaced: a new one is added, one
        whose title or text changed is replaced, and one that is kept as given already is left untouched, so saving the
        same articles again changes nothing. Then it drops what retention no longer keeps of the stocks named.
        """
        ...

    async def latest(self, stock_id: str, limit: int) -> list[Article]:
        """
        The stock's kept news, newest first, at most limit, each read at the time it was first kept: every kept article
        but a document of record (InformationSource.is_reference), which is no news of a day and is read by `references`.
        """
        ...

    async def find(self, stock_id: str, keys: Collection[str]) -> list[Article]:
        """The stock's kept articles of those keys, in no order. A key that is not kept is left out."""
        ...

    async def references(self, stock_id: str) -> list[Article]:
        """The stock's kept documents of record (InformationSource.is_reference), such as its annual report's sections, in no order."""
        ...

    async def stock_ids(self) -> list[str]:
        """Every stock with a kept article, in stock id order."""
        ...
