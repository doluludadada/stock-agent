from sqlmodel import Field, SQLModel

from a_domain.model.analysis.ai_analysis_report import AiAnalysisReport
from a_domain.model.indicators.technical_indicators import TechnicalIndicators
from a_domain.model.market.article import Article
from a_domain.model.market.ohlcv import Ohlcv
from a_domain.types.enums import MarketType


class Stock(SQLModel):
    """
    Stock Domain Model.

    Serves as both entity identity and mutable pipeline context.
    During pipeline execution, fields are progressively populated
    (ohlcv → indicators → scores → signal).
    """

    # --------------------------------- Identity --------------------------------- #
    stock_id: str
    market: MarketType = Field(default=MarketType.TWSE)
    name: str | None = None
    industry: str | None = None

    # ----------------------------------- Data ----------------------------------- #
    ohlcv: list[Ohlcv] = Field(default_factory=list)
    articles: list[Article] = Field(default_factory=list)

    # -------------------------------- Analysis ---------------------------------- #
    # TODO: Actually it shoudnt be None
    indicators: TechnicalIndicators | None = None
    
    # TODO: move blow stuffs those stuff to StockWatchlist?
    hard_failures: list[str] = Field(default_factory=list)
    soft_failures: list[str] = Field(default_factory=list)
    observations: list[str] = Field(default_factory=list)
    
    technical_score: int | None = None

    # -------------------------------- Sentiment --------------------------------- #
    historical_context: str = ""  # It should be saved in RAG database.
    analysis_report: AiAnalysisReport | None = None
    ai_score: int | None = None

    # -------------------------------- Decision ---------------------------------- #
    combined_score: int = 50

    # -------------------------------- Shortcuts --------------------------------- #
    @property
    def today(self) -> Ohlcv | None:
        return self.ohlcv[-1] if self.ohlcv else None

    @property
    def yesterday(self) -> Ohlcv | None:
        return self.ohlcv[-2] if len(self.ohlcv) >= 2 else None

    @property
    def current_price(self) -> float | None:
        return self.today.close if self.today else None

    @property
    def current_volume(self) -> int | None:
        return self.today.volume if self.today else None

    @property
    def is_eliminated(self) -> bool:
        return len(self.hard_failures) > 0
