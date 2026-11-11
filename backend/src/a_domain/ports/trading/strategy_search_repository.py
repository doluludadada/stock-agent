from typing import Protocol

from a_domain.rules.technical.search import StrategySearch


class IStrategySearchRepository(Protocol):
    """The strategy searches run on this installation, kept for the owner to read and to adopt a winner from."""

    async def save(self, search: StrategySearch) -> str:
        """Saves the search and answers where, in words its reader can follow to it."""
        ...
