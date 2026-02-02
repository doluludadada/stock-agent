from datetime import datetime
from decimal import Decimal

from sqlmodel import Field, SQLModel

from src.a_domain.types.enums import SignalAction, SignalSource


class TradeSignal(SQLModel):
    """
    The final output of the pipeline, ready for execution.
    """

    stock_id: str
    action: SignalAction  # BUY/SELL/HOLD
    price_at_signal: Decimal
    source: SignalSource  # HYBRID/TECHNICAL
    score: int
    reason: str

    # Execution details (Optional, populated by generator)
    quantity: int = Field(default=0)
    stop_loss_price: Decimal | None = Field(default=None)

    generated_at: datetime = Field(default_factory=datetime.now)
