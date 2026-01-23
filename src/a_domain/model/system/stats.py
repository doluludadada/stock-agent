# TODO: 未來功能 - 系統監控統計 (目前未使用)
from datetime import date, datetime
from uuid import UUID, uuid4

from sqlmodel import Field, SQLModel


class SystemStats(SQLModel):
    """
    A comprehensive daily report card for the trading system.
    Stored in DB to analyse system performance over time.
    """

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    system_date: date = Field(default_factory=datetime.date.today, index=True)

    # ------------------------------ Funnel Metrics ------------------------------ #
    total_market_targets: int = Field(default=0, description="Total stocks in market")
    scanned_count: int = Field(default=0, description="Stocks processed by Level 1")
    passed_screening_count: int = Field(default=0, description="Stocks passed Level 1")

    # -------------------------------- AI Metrics -------------------------------- #
    ai_analysis_count: int = Field(default=0, description="Stocks sent to LLM")
    avg_confidence_score: float | None = Field(default=None, description="Market sentiment proxy")

    # ------------------------------ Action Metrics ------------------------------ #
    buy_signals_generated: int = Field(default=0)
    sell_signals_generated: int = Field(default=0)
    orders_submitted: int = Field(default=0)

    # ------------------------------- System Health ------------------------------ #
    error_count: int = Field(default=0)
    execution_time_seconds: float = Field(default=0.0)

    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)

    def increment_scan(self):
        self.scanned_count += 1

    def increment_pass(self):
        self.passed_screening_count += 1

    def record_error(self):
        self.error_count += 1
