# backend/src/c_infrastructure/database/models/trade_signal_dto.py
from typing import ClassVar
from uuid import UUID, uuid4

from pydantic import model_validator
from sqlmodel import Field

from a_domain.model.trading.signal import TradeSignal


class TradeSignalDTO(TradeSignal, table=True):
    """Infrastructure Database Model for Trade Signals."""

    __tablename__: ClassVar[str] = "trade_signals"  # pyright: ignore[reportIncompatibleVariableOverride]
    id: UUID = Field(default_factory=uuid4, primary_key=True)

    @model_validator(mode="after")
    def _check_invariants(self) -> "TradeSignalDTO":
        assert 0 <= self.score <= 100, f"score must be 0-100, got {self.score}"
        assert self.quantity >= 0, f"quantity must be >= 0, got {self.quantity}"
        assert self.price_at_signal > 0, f"price must be positive, got {self.price_at_signal}"
        return self
