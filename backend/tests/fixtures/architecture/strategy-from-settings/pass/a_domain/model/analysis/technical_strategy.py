from dataclasses import dataclass

from a_domain.model.analysis.technical_rule import TechnicalRule


@dataclass(frozen=True)
class TechnicalStrategy:
    strategy_id: str
    rules: tuple[TechnicalRule, ...]

    def rule_ids(self) -> list[str]:
        return [rule.rule_id for rule in self.rules]
