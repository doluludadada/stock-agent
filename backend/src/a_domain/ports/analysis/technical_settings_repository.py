from typing import Protocol

from a_domain.model.analysis.technical_settings import TechnicalSettings


class ITechnicalSettingsRepository(Protocol):
    """
    Provides the user's technical-analysis settings.

    Each workflow loads one immutable settings snapshot.
    Changes saved during a workflow apply to the next workflow.
    """

    async def load(self) -> TechnicalSettings: ...

    async def save(self, settings: TechnicalSettings) -> None: ...
