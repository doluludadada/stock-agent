from pydantic import BaseModel
from pydantic_settings import BaseSettings


class TradingSettings(BaseModel):
    max_positions: int = 5


class LineSettings(BaseSettings):
    channel_secret: str | None = None


class AppSettings(BaseSettings):
    trading: TradingSettings = TradingSettings()
