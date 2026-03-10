from datetime import datetime

from pydantic import BaseModel, Field

from a_domain.types.enums import SignalAction, SignalSource


class TradeSignal(BaseModel):
    stock_id: str
    action: SignalAction
    price_at_signal: float
    source: SignalSource
    score: int
    reason: str
    quantity: int = Field(default=0)
    stop_loss_price: float | None = Field(default=None)
    generated_at: datetime = Field(default_factory=datetime.now)
