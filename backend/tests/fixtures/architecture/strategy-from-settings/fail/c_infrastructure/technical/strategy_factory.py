from a_domain.rules.technical import strategy
from a_domain.rules.technical.strategy import TechnicalStrategy


class StrategyFactory:
    def nightly(self) -> TechnicalStrategy:
        return TechnicalStrategy(
            strategy_id="nightly",
            rules=(strategy.TechnicalRule(name="above_ma20"),),
        )
