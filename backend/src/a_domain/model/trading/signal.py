from datetime import datetime, timezone

from sqlmodel import Field, SQLModel

from a_domain.types.enums import SignalSource, TradeAction


class TradeSignal(SQLModel):
    """Analysis decision generated before broker order construction."""

    stock_id: str
    action: TradeAction
    price_at_signal: float
    source: SignalSource
    score: int
    reason: str
    quantity: int = Field(default=0)
    stop_loss_price: float | None = Field(default=None)
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
