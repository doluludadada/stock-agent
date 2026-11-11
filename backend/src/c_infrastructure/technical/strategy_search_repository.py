from dataclasses import replace
from pathlib import Path
from typing import override

from pydantic import TypeAdapter

from a_domain.ports.trading.strategy_search_repository import IStrategySearchRepository
from a_domain.rules.technical.search import StrategySearch
from a_domain.rules.technical.strategy import TechnicalStrategy


class FileStrategySearchRepository(IStrategySearchRepository):
    """
    Each search in a folder of its own under `folder`, named after when it started, its level and its random seed:
    search.json holds the whole search, and one file per winner holds its strategy in the shape of
    config/strategies/<id>.json, its id and file name telling the origin, the level, the seed and the winner's rank,
    so that it can be copied there or into the settings as it is. The scores it buys and sells at are in search.json.
    """

    def __init__(self, folder: Path) -> None:
        self._folder = folder
        self._search_json = TypeAdapter(StrategySearch)
        self._strategy_json = TypeAdapter(TechnicalStrategy)

    @override
    async def save(self, search: StrategySearch) -> str:
        origin, level, seed = search.origin.candidate.strategy, search.inputs.level, search.inputs.random_seed
        folder = self._folder / f"{search.started_at:%Y%m%d-%H%M%S}-{level}-seed{seed}"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "search.json").write_bytes(self._search_json.dump_json(search, indent=1))

        for rank, winner in enumerate(search.winners, start=1):
            strategy_id = f"{origin.strategy_id}_{level}_{seed}_{rank}"[:40]
            name = f"{origin.name}, {level} seed {seed}, winner {rank}"
            strategy = replace(winner.candidate.strategy, strategy_id=strategy_id, name=name)
            (folder / f"{strategy_id}.json").write_bytes(self._strategy_json.dump_json(strategy, indent=2))

        return str(folder)
