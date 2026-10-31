from a_domain.model.analysis.technical_rule import TechnicalRule


class NightlyScan:
    async def execute(self) -> TechnicalRule:
        return TechnicalRule(rule_id="volume_spike")
