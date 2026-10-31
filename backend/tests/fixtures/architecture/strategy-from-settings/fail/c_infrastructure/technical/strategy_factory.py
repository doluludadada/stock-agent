from a_domain.model.analysis import technical_rule
from a_domain.model.analysis.technical_strategy import TechnicalStrategy


class StrategyFactory:
    def nightly(self) -> TechnicalStrategy:
        return TechnicalStrategy(
            strategy_id="nightly",
            rules=(technical_rule.TechnicalRule(rule_id="above_ma20"),),
        )
