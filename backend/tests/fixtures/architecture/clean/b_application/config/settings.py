from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict


class ShippingSettings(BaseModel):
    minimum_total: int = 1000
    excluded_regions: frozenset[str] = frozenset()


class AppSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env")

    database_url: str = "sqlite+aiosqlite:///orders.db"
    shipping: ShippingSettings = ShippingSettings()
