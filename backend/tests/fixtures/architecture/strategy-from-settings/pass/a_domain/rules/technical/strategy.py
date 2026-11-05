from pydantic.dataclasses import dataclass


@dataclass(frozen=True)
class TechnicalRule:
    name: str


@dataclass(frozen=True)
class TechnicalStrategy:
    strategy_id: str
    rules: tuple[TechnicalRule, ...]


@dataclass(frozen=True)
class TechnicalSettings:
    active_strategy_id: str
    strategies: tuple[TechnicalStrategy, ...]
