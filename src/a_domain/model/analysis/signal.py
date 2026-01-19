from datetime import datetime
from decimal import Decimal
from sqlmodel import SQLModel, Field
from src.a_domain.types.enums import SignalAction, SignalSource


class TradeSignal(SQLModel):
    """
    The output of the funnel analysis.
    """

    symbol: str
    action: SignalAction
    price_at_signal: Decimal
    source: SignalSource
    score: int = Field(ge=0, le=100, description="Confidence score 0-100")
    reason: str | None = None
    generated_at: datetime = Field(default_factory=datetime.now)
