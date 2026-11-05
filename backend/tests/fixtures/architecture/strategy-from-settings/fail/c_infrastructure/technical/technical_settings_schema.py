from pydantic import BaseModel

from a_domain.rules.technical.strategy import TechnicalRule
from a_domain.rules.technical.strategy import TechnicalStrategy


class StrategySchema(BaseModel):
    strategy_id: str
    rule_ids: list[str]

    def to_domain(self) -> TechnicalStrategy:
        return TechnicalStrategy(strategy_id=self.strategy_id, rules=tuple(TechnicalRule(name=rule_id) for rule_id in self.rule_ids))
