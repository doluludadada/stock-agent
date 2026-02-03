from dataclasses import dataclass, field
from decimal import Decimal

from backend.src.a_domain.model.analysis.ai_sentiment import AiSentiment
from backend.src.a_domain.model.indicators.technical_indicators import TechnicalIndicators
from backend.src.a_domain.model.market.article import Article
from backend.src.a_domain.model.market.ohlcv import Ohlcv
from backend.src.a_domain.model.market.stock import Stock
from backend.src.a_domain.types.enums import AnalysisStage, CandidateSource


@dataclass
class AnalysisContext:
    """
    The 'Case File' that travels through the pipeline.
    """

    # --- Identity ---
    stock: Stock
    source: CandidateSource
    trigger_reason: str
    stage: AnalysisStage = AnalysisStage.PENDING

    # --- Data (Collected) ---
    current_price: Decimal | None = None
    ohlcv_data: list[Ohlcv] = field(default_factory=list)
    articles: list[Article] = field(default_factory=list)

    # --- Technical State ---
    indicators: TechnicalIndicators | None = None

    # --- Analysis Result ---
    technical_failures: list[str] = field(default_factory=list)

    technical_score: int = 0
    sentiment_score: int = 0
    sentiment_report: AiSentiment | None = None
    combined_score: int = 0


