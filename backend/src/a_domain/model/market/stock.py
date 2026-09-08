# backend/src/a_domain/model/market/stock.py

from sqlmodel import Field, SQLModel

from a_domain.model.analysis.ai_analysis_report import AiAnalysisReport
from a_domain.model.analysis.technical_report import TechnicalReport
from a_domain.model.indicators.technical_indicators import TechnicalIndicators
from a_domain.model.market.article import Article
from a_domain.model.market.ohlcv import Ohlcv
from a_domain.types.enums import MarketType, WatchlistType


class Stock(SQLModel):
    """
    Stock Domain Model.

    Serves as both entity identity and mutable pipeline context.
    During pipeline execution, fields are progressively populated.
    """

    # --------------------------------- Identity --------------------------------- #
    stock_id: str
    name: str | None = None
    market: MarketType = Field(default=MarketType.TWSE)
    industry: str | None = None

    # ----------------------------------- Data ----------------------------------- #
    ohlcv: list[Ohlcv] = Field(default_factory=list)
    articles: list[Article] = Field(default_factory=list)

    # -------------------------------- Analysis ---------------------------------- #
    indicators: TechnicalIndicators = Field(default_factory=TechnicalIndicators)
    technical_report: TechnicalReport | None = None
    ai_report: AiAnalysisReport | None = None
    composite_score: int | None = None

    watchlist_types: set[WatchlistType] = Field(default_factory=set)

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
    def technical_score(self) -> int | None:
        return self.technical_report.score if self.technical_report else None

    @property
    def ai_score(self) -> int | None:
        return self.ai_report.score if self.ai_report else None

    @property
    def is_eliminated(self) -> bool:
        return bool(self.technical_report and not self.technical_report.passed)

    @property
    def hard_failures(self) -> list[str]:
        return self.technical_report.hard_failures if self.technical_report else []

    @property
    def soft_failures(self) -> list[str]:
        return self.technical_report.soft_failures if self.technical_report else []

    @property
    def observations(self) -> list[str]:
        return self.technical_report.observations if self.technical_report else []
