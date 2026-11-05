from typing import Protocol

from a_domain.rules.technical.strategy import TechnicalSettings


class ITechnicalSettingsRepository(Protocol):
    """Each owner's saved technical settings. One owner's settings never read or change another owner's."""

    async def load(self, owner_id: str, initial: TechnicalSettings) -> TechnicalSettings:
        """
        The owner's saved settings. An owner with none gets `initial` saved first with revision 0, once even when two
        processes ask at the same time; a later load never resets what the owner saved.
        """
        ...

    async def save(self, owner_id: str, settings: TechnicalSettings) -> TechnicalSettings:
        """
        Replaces the owner's settings, in one transaction, when settings.revision is still the saved revision, and
        returns them with the next revision. Otherwise raises TechnicalSettingsConflictError and changes nothing.
        """
        ...
