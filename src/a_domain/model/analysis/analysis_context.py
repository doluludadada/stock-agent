from dataclasses import dataclass, field
from decimal import Decimal

from src.a_domain.model.analysis.analysis_report import AnalysisReport
from src.a_domain.model.analysis.screening_result import ScreeningResult
from src.a_domain.model.analysis.technical_indicators import TechnicalIndicators
from src.a_domain.model.market.article import Article
from src.a_domain.model.market.ohlcv import Ohlcv
from src.a_domain.model.market.stock import Stock


@dataclass
class AnalysisContext:
    """
    Container for all data collected and computed for a single stock.
    Passed between pipeline stages. Mutable to allow progressive enrichment.
    """

    stock: Stock
    ohlcv_data: list[Ohlcv] = field(default_factory=list)
    articles: list[Article] = field(default_factory=list)
    current_price: Decimal | None = None

    # Process stage results
    indicators: TechnicalIndicators | None = None
    screening_result: ScreeningResult | None = None
    sentiment_report: AnalysisReport | None = None

    # Combined scores (0-100)
    technical_score: int | None = None
    sentiment_score: int | None = None
    combined_score: int | None = None
