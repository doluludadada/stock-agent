from typing import Protocol

from a_domain.rules.technical.strategy import TechnicalSettings


class ITechnicalSettingsRepository(Protocol):
    async def load(self) -> TechnicalSettings: ...
