from collections.abc import Iterator
from typing import Self

from pydantic.dataclasses import dataclass

from a_domain.model.fundamentals.eps import Eps, EpsUnavailable
from a_domain.model.market.ohlcv import Ohlcv
from a_domain.model.market.stock import Stock
from a_domain.types.enums import PeNotApplicableReason, ScenarioName
from a_domain.types.values import PositiveFiniteFloat


@dataclass(frozen=True)
class PeMedian:
    value: float
    sample_size: int


@dataclass(frozen=True)
class PeRatio:
    """A computable P/E. Holding a positive price and EPS makes it the only input a fair price accepts."""

    price: PositiveFiniteFloat
    eps: PositiveFiniteFloat

    @property
    def value(self) -> float:
        return self.price / self.eps


@dataclass(frozen=True)
class ValuationScenario:
    name: ScenarioName
    target_pe: PositiveFiniteFloat
    assumption: str
    pe: PeRatio

    @property
    def fair_price(self) -> float:
        return self.pe.eps * self.target_pe

    @property
    def gap(self) -> float:
        return self.fair_price - self.pe.price

    @property
    def undervaluation(self) -> float:
        """(fair price − price) ÷ price. Positive is undervalued, negative is overvalued."""
        return self.gap / self.pe.price


@dataclass(frozen=True)
class FairPriceRange:
    """Three scenarios: the user's target P/E, and the configured spread below and above it."""

    conservative: ValuationScenario
    base: ValuationScenario
    optimistic: ValuationScenario

    def __iter__(self) -> Iterator[ValuationScenario]:
        return iter((self.conservative, self.base, self.optimistic))


@dataclass(frozen=True)
class StockValuation:
    """
    One stock's valuation before any user assumption: its EPS, the exchange's latest official close, and what
    StockValuationRule derived from them when the market was loaded.

    EPS is read through the stock, whose only writer is FundamentalsFeed.
    """

    stock: Stock
    close: Ohlcv | None
    current_pe: PeRatio | PeNotApplicableReason
    close_is_fresh: bool
    warnings: tuple[str, ...]
    industry_median_pe: PeMedian | None = None
    """The median P/E of the stock's industry over stocks with a fresh close: a reference only, never a target."""

    @property
    def eps(self) -> Eps | EpsUnavailable:
        return self.stock.eps

    @property
    def needs_target_pe(self) -> bool:
        """Its P/E is computable, so valuing it needs the user's target P/E. Otherwise it has no fair price to compute."""
        return isinstance(self.current_pe, PeRatio)

    @property
    def price_text(self) -> str:
        if self.close is None:
            return "no valid close"

        return f"{self.close.close:,.2f} TWD ({self.close.ts:%Y-%m-%d} close, published by the exchange)"

    @property
    def pe_text(self) -> str:
        match self.current_pe:
            case PeRatio() as pe:
                return f"{pe.value:.2f}x"
            case PeNotApplicableReason() as reason:
                return reason.label


@dataclass(frozen=True)
class ReportSection:
    title: str
    lines: tuple[str, ...]


@dataclass(frozen=True)
class ValuationReport:
    """A stock valued at the user's target P/E. Scenarios exist exactly when the current P/E is computable."""

    valuation: StockValuation
    target_pe: PositiveFiniteFloat | None
    """The user's P/E assumption for this run. It is never persisted."""

    fair_value: FairPriceRange | PeNotApplicableReason

    @property
    def stock(self) -> Stock:
        return self.valuation.stock

    @property
    def base(self) -> ValuationScenario | None:
        """The scenario at the user's target P/E, or None when no fair price applies."""
        return self.fair_value.base if isinstance(self.fair_value, FairPriceRange) else None

    @property
    def undervaluation(self) -> float | None:
        return self.base.undervaluation if self.base is not None else None

    @property
    def appears_undervalued(self) -> bool:
        return self.undervaluation is not None and self.undervaluation > 0


@dataclass(frozen=True)
class ValuationExplanation:
    """A valuation report plus the AI's prose. The AI contributes text lists only, never a number."""

    report: ValuationReport
    higher_pe_factors: tuple[str, ...]
    pe_derating_risks: tuple[str, ...]
    data_gaps: tuple[str, ...]
    summary: str
    raw_response: str

    @classmethod
    def without_ai(cls, report: ValuationReport, reason: str) -> Self:
        return cls(report=report, higher_pe_factors=(), pe_derating_risks=(), data_gaps=(reason,), summary="", raw_response="")
