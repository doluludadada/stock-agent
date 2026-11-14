from pydantic.dataclasses import dataclass


@dataclass(frozen=True)
class TechnicalSettings:
    active_strategy_id: str
    strategy_ids: tuple[str, ...]

    @property
    def is_selected(self) -> bool:
        return self.active_strategy_id in self.strategy_ids
