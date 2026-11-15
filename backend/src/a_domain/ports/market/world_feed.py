from typing import Protocol

from a_domain.model.market.article import Article
from a_domain.model.market.world_indicator import IndicatorReading


class IWorldFeed(Protocol):
    """
    What the site reads of the world outside Taiwan's exchanges, from the feeds the settings name and the site's
    audience may read: publishers' feeds of world news, and public agencies' tables of market indicators. A feed that
    is down, refuses or serves what cannot be read is logged and left out; the others are still answered.
    """

    async def fetch_news(self) -> list[Article]:
        """
        The items the world news feeds list now, under MarketScope.WORLD, each once however many feeds list it: its
        title and the feed's own summary as plain text, its address and when it was published. No article's page is read.
        """
        ...

    async def fetch_indicators(self) -> list[IndicatorReading]:
        """Each world indicator's readings of the days its source lists now, none with the reading before it."""
        ...
