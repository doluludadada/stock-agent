from a_domain.ports.analysis.technical_settings_repository import ITechnicalSettingsRepository
from a_domain.rules.technical.strategy import TechnicalSettings
from b_application.config.app_config import AppConfig


class TechnicalSettingsEditor:
    """
    The settings editor's step, for the owner of the settings repository it was given. Given replacement settings it
    saves them, unless another save came after the revision they carry (TechnicalSettingsConflictError, nothing saved).
    It returns the owner's settings as they are now saved; an owner who never saved gets the initial settings first.
    """

    def __init__(self, technical_settings_repository: ITechnicalSettingsRepository, config: AppConfig) -> None:
        self._technical_settings_repository = technical_settings_repository
        self._initial_settings = config.technical.initial_settings

    async def execute(self, replacement: TechnicalSettings | None = None) -> TechnicalSettings:
        if replacement is None:
            return await self._technical_settings_repository.load(self._initial_settings)

        return await self._technical_settings_repository.save(replacement)
