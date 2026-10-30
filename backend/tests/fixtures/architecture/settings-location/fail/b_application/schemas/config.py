from pydantic import BaseModel
from pydantic_settings import BaseSettings


class TradingConfig(BaseModel):
    max_positions: int = 5


class AppConfig(BaseSettings):
    trading: TradingConfig = TradingConfig()
