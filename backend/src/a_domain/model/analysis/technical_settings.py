# a_domain/model/analysis/technical_settings.py

from dataclasses import dataclass

from icontract import invariant

from a_domain.rules.technical.strategy import TechnicalStrategy


@invariant(lambda self: len({strategy.strategy_id for strategy in self.strategies}) == len(self.strategies))
@invariant(lambda self: self.active_strategy_id in {strategy.strategy_id for strategy in self.strategies})
@invariant(lambda self: self.buzz_strategy_id in {strategy.strategy_id for strategy in self.strategies})
@dataclass(frozen=True)
class TechnicalSettings:
    active_strategy_id: str
    buzz_strategy_id: str
    strategies: tuple[TechnicalStrategy, ...]

    @property
    def active_strategy(self) -> TechnicalStrategy:
        return self.get_strategy(self.active_strategy_id)

    @property
    def buzz_strategy(self) -> TechnicalStrategy:
        return self.get_strategy(self.buzz_strategy_id)

    def get_strategy(self, strategy_id: str) -> TechnicalStrategy:
        for strategy in self.strategies:
            if strategy.strategy_id == strategy_id:
                return strategy

        raise KeyError(f"Technical strategy not found: {strategy_id}")
