from datetime import datetime
from decimal import Decimal

from backend.src.a_domain.types.enums import SignalAction, SignalSource
from sqlmodel import Field, SQLModel


class TradeSignal(SQLModel):
    stock_id: str
    action: SignalAction
    price_at_signal: Decimal
    source: SignalSource
    score: int
    reason: str
    quantity: int = Field(default=0)
    stop_loss_price: Decimal | None = Field(default=None)
    generated_at: datetime = Field(default_factory=datetime.now)
