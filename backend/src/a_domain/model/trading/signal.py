from datetime import UTC, datetime
from typing import Self

from pydantic import model_validator
from sqlmodel import Field, SQLModel

from a_domain.model.analysis.ai_analysis_report import AiAnalysisReport
from a_domain.model.analysis.technical_report import TechnicalReport
from a_domain.model.market.stock import Stock
from a_domain.types.enums import SignalSource, TradeAction
from a_domain.types.ids import DecisionId, new_decision_id


class TradeSignal(SQLModel):
    """
    A trading decision and the evidence it was made on.

    `decision_id` identifies the decision: the order that executes it and the saved signal row
    both carry it. The evidence fields are what an audit needs to rebuild the decision: the quote
    that priced it, the daily history the indicators ran on, and the technical and AI reports.
    """

    decision_id: DecisionId = Field(default_factory=new_decision_id)

    stock_id: str
    action: TradeAction
    source: SignalSource
    score: int
    reason: str
    quantity: int = Field(default=0, ge=0)
    stop_loss_price: float | None = Field(default=None)
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    price_at_signal: float = Field(gt=0)
    price_observed_at: datetime
    """Timestamp of the quote behind price_at_signal (the realtime bar, or the last daily bar without one)."""

    history_until: datetime | None = None
    """Timestamp of the last daily bar the technical indicators were computed from."""

    technical_report: TechnicalReport | None = None
    ai_report: AiAnalysisReport | None = None

    @model_validator(mode="after")
    def _orderable_signals_have_shares(self) -> Self:
        if self.action != TradeAction.HOLD and self.quantity <= 0:
            raise ValueError(f"{self.action} signal needs a positive quantity")

        return self

    @classmethod
    def of(
        cls,
        stock: Stock,
        action: TradeAction,
        source: SignalSource,
        score: int,
        reason: str,
        quantity: int = 0,
        stop_loss_price: float | None = None,
    ) -> Self:
        """Decides on `stock` as it is now: its current quote prices the signal and its reports become the evidence."""
        price = stock.current_price
        observed_at = stock.latest_market_data_at

        if price is None or observed_at is None:
            raise ValueError(f"Signal for {stock.stock_id} needs a current price")

        return cls(
            stock_id=stock.stock_id,
            action=action,
            source=source,
            score=score,
            reason=reason,
            quantity=quantity,
            stop_loss_price=stop_loss_price,
            price_at_signal=price,
            price_observed_at=observed_at,
            history_until=stock.today.ts if stock.today else None,
            technical_report=stock.technical_report,
            ai_report=stock.ai_report,
        )
