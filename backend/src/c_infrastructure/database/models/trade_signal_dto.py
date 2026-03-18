# backend/src/c_infrastructure/database/models/trade_signal_dto.py
from typing import ClassVar
from uuid import UUID, uuid4

from sqlmodel import Field

from a_domain.model.trading.signal import TradeSignal


class TradeSignalDTO(TradeSignal, table=True):
    """Infrastructure Database Model for Trade Signals."""

    __tablename__: ClassVar[str] = "trade_signals"
    id: UUID = Field(default_factory=uuid4, primary_key=True)
