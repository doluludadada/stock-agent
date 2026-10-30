import pydantic_settings


class TechnicalSettings(pydantic_settings.BaseSettings):
    window: int = 14
