from a_domain.ports.analysis.technical_settings_repository import ITechnicalSettingsRepository
from a_domain.rules.technical.strategy import TechnicalSettings
from b_application.config.app_config import AppConfig


class TechnicalSettingsLoader:
    """
    The settings editor's read, for the owner of the settings repository it was given: the owner's settings as they are
    saved now. An owner who never saved gets the initial settings of technical.initial_settings saved first, which the
    Pipeline, holding no setting, cannot hand the repository.
    """

    def __init__(self, technical_settings_repository: ITechnicalSettingsRepository, config: AppConfig) -> None:
        self._technical_settings_repository = technical_settings_repository
        self._initial_settings = config.technical.initial_settings

    async def execute(self) -> TechnicalSettings:
        return await self._technical_settings_repository.load(self._initial_settings)
