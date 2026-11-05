from pydantic import TypeAdapter

from a_domain.rules.technical.strategy import TechnicalSettings


class SqlTechnicalSettingsRepository:
    def __init__(self) -> None:
        self._settings = TypeAdapter(TechnicalSettings)
