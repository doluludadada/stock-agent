# backend/src/c_infrastructure/technical/yaml_technical_settings_repository.py

from pathlib import Path

import yaml

from a_domain.model.analysis.technical_settings import TechnicalSettings
from a_domain.ports.analysis.technical_settings_repository import ITechnicalSettingsRepository
from c_infrastructure.technical.technical_settings_schema import TechnicalSettingsSchema


class YamlTechnicalSettingsRepository(ITechnicalSettingsRepository):
    """
    YAML-backed technical settings repository.

    Settings are loaded on every workflow start so the next workflow always
    receives the latest saved configuration.
    """

    def __init__(self, settings_path: Path) -> None:
        self._settings_path = settings_path

    async def load(self) -> TechnicalSettings:
        if not self._settings_path.exists():
            raise FileNotFoundError(f"Technical settings file not found: {self._settings_path}")

        with self._settings_path.open(encoding="utf-8") as settings_file:
            raw_settings = yaml.safe_load(settings_file) or {}

        settings_schema = TechnicalSettingsSchema.model_validate(raw_settings)

        return settings_schema.to_domain()

    async def save(self, settings: TechnicalSettings) -> None:
        raise NotImplementedError
