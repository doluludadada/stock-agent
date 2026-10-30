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

    async def reset(self) -> None:
        """Forgets the saved settings, so the next load returns the shipped defaults. Resetting twice is harmless."""
        ...
