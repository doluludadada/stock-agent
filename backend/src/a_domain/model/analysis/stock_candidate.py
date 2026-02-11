from dataclasses import dataclass, field
from decimal import Decimal

from backend.src.a_domain.model.analysis.ai_sentiment import AiSentiment
from backend.src.a_domain.model.indicators.technical_indicators import TechnicalIndicators
from backend.src.a_domain.model.market.article import Article
from backend.src.a_domain.model.market.ohlcv import Ohlcv
from backend.src.a_domain.model.market.stock import Stock
from backend.src.a_domain.types.enums import AnalysisStage, CandidateSource


@dataclass
class StockCandidate:
    """
    Represents a stock being evaluated in the pipeline.
    Accumulates state as it flows through each use case.

    Written by:
        - SelectCandidates  → stock, source, trigger_reason
        - CollectPrices     → ohlcv_data
        - FilterCandidates  → indicators, hard/soft_failures, observations, technical_score, stage
        - CollectArticles   → articles
        - AnalyzeSentiment  → sentiment_report, sentiment_score
        - GenerateSignals   → combined_score, stage
    """

    # --- Identity (set at creation) ---
    stock: Stock
    source: CandidateSource
    trigger_reason: str = ""
    stage: AnalysisStage = AnalysisStage.PENDING

    # --- Market Data (set by CollectPrices) ---
    ohlcv_data: list[Ohlcv] = field(default_factory=list)

    # --- Technical Analysis (set by FilterCandidates) ---
    indicators: TechnicalIndicators | None = None
    hard_failures: list[str] = field(default_factory=list)
    soft_failures: list[str] = field(default_factory=list)
    observations: list[str] = field(default_factory=list)
    technical_score: int | None = None

    # --- Sentiment Analysis (set by AnalyzeSentiment) ---
    articles: list[Article] = field(default_factory=list)
    historical_context: str = ""
    sentiment_report: AiSentiment | None = None
    sentiment_score: int | None = None

    # --- Final Decision (set by GenerateSignals) ---
    combined_score: int = 50

    # --- Computed Properties ---

    @property
    def current_price(self) -> Decimal | None:
        return self.ohlcv_data[-1].close_price if self.ohlcv_data else None

    @property
    def current_volume(self) -> int | None:
        return self.ohlcv_data[-1].volume if self.ohlcv_data else None

    @property
    def is_eliminated(self) -> bool:
        return len(self.hard_failures) > 0
