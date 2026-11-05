from a_domain.rules.technical.strategy import TechnicalRule


class NightlyScan:
    async def execute(self) -> TechnicalRule:
        return TechnicalRule(name="volume_spike")
