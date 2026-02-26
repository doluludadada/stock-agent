from decimal import Decimal

from backend.src.a_domain.model.analysis.ai_sentiment import AiSentiment
from backend.src.a_domain.model.indicators.technical_indicators import TechnicalIndicators
from backend.src.a_domain.model.market.article import Article
from backend.src.a_domain.model.market.ohlcv import Ohlcv
from backend.src.a_domain.types.enums import AnalysisStage, CandidateSource, MarketType
from sqlmodel import Field, SQLModel


class Stock(SQLModel):
    """
    Stock Domain Model.
    Pure data container with minimal shortcut properties.
    """

    # --------------------------------- Identity --------------------------------- #
    stock_id: str = Field(primary_key=True, index=True)
    market: MarketType = Field(default=MarketType.TWSE)
    name: str | None = None
    industry: str | None = None

    # --------------------------------- Pipeline --------------------------------- #
    source: CandidateSource | None = Field(default=None, schema_extra={"ignore": True})
    trigger_reason: str = Field(default="", schema_extra={"ignore": True})
    stage: AnalysisStage = Field(default=AnalysisStage.PENDING, schema_extra={"ignore": True})

    # ----------------------------------- Data ----------------------------------- #
    ohlcv: list[Ohlcv] = Field(default_factory=list)
    articles: list[Article] = Field(default_factory=list)

    # -------------------------------- Analysis ---------------------------------- #
    indicators: TechnicalIndicators | None = Field(default=None, schema_extra={"ignore": True})

    hard_failures: list[str] = Field(default_factory=list, schema_extra={"ignore": True})
    soft_failures: list[str] = Field(default_factory=list, schema_extra={"ignore": True})
    observations: list[str] = Field(default_factory=list, schema_extra={"ignore": True})

    technical_score: int | None = Field(default=None, schema_extra={"ignore": True})

    # -------------------------------- Sentiment --------------------------------- #
    historical_context: str = Field(default="", schema_extra={"ignore": True})
    sentiment_report: AiSentiment | None = Field(default=None, schema_extra={"ignore": True})
    sentiment_score: int | None = Field(default=None, schema_extra={"ignore": True})

    # -------------------------------- Decision ---------------------------------- #
    combined_score: int = Field(default=50, schema_extra={"ignore": True})

    # -------------------------------- Shortcuts --------------------------------- #
    @property
    def today(self) -> Ohlcv | None:
        return self.ohlcv[-1] if self.ohlcv else None

    @property
    def yesterday(self) -> Ohlcv | None:
        return self.ohlcv[-2] if len(self.ohlcv) >= 2 else None

    @property
    def current_price(self) -> Decimal | None:
        return self.today.close if self.today else None

    @property
    def current_volume(self) -> int | None:
        return self.today.volume if self.today else None

    @property
    def is_eliminated(self) -> bool:
        return len(self.hard_failures) > 0

    @property
    def display_name(self) -> str:
        if self.name:
            return f"{self.stock_id} {self.name}"
        return self.stock_id
