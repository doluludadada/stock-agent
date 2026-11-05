from pydantic import BaseModel, ConfigDict

from a_domain.rules.technical.strategy import TechnicalSettings


class OrderResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    total: int
    free_shipping: bool


class TechnicalSettingsRequest(BaseModel):
    settings: TechnicalSettings
