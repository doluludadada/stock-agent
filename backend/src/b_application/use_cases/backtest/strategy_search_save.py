from a_domain.ports.trading.strategy_search_repository import IStrategySearchRepository
from a_domain.rules.technical.search import StrategySearch


class StrategySearchSave:
    """Saves a strategy search for the owner to read, and answers where."""

    def __init__(self, search_repository: IStrategySearchRepository) -> None:
        self._search_repository = search_repository

    async def execute(self, search: StrategySearch) -> str:
        return await self._search_repository.save(search)
