from datetime import datetime
from uuid import UUID, uuid4

from sqlmodel import Field, SQLModel


class AnalysisReport(SQLModel):
    """
    Stores the detailed result of the Level 2 AI Analysis.
    This serves as the 'evidence' for why a signal was generated.
    """

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    stock_id: str = Field(index=True)
    analysis_date: datetime = Field(default_factory=datetime.now)

    # Quantitative Summary from AI
    confidence_score: int = Field(ge=0, le=100, description="AI confidence 0-100")

    # Qualitative Insights
    bullish_factors: str  # Stored as text or JSON string
    bearish_factors: str

    # The raw reasoning returned by the LLM (for debugging/audit)
    raw_llm_response: str
