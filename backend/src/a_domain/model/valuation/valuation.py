from __future__ import annotations

import math
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date
from enum import StrEnum, auto

from icontract import invariant, require

from a_domain.model.fundamentals.eps import Eps, EpsUnavailable
from a_domain.model.market.ohlcv import Ohlcv
from a_domain.model.market.stock import Stock
from a_domain.rules.collect.freshness import DailyCloseFreshnessRule

LABEL = "基於指定本益比的估值"
NOT_INVESTMENT_ADVICE = (
    "本報告僅為基於指定本益比的估值試算與資料整理，不構成投資建議；估值結果取決於所設定的本益比假設，並非客觀真實價值。"
)
LOW_PE_CAVEAT = "低本益比可能反映獲利成長下降、一次性收益墊高 EPS 或市場與產業風險；低本益比本身不是買進訊號。"
AI_NOT_PROVIDED = "（AI 未提供）"
UNDERVALUATION_FORMULA = "低估幅度 = (合理價 − 目前股價) ÷ 目前股價；正值為低估，負值為高估"


class PeNotApplicableReason(StrEnum):
    EPS_UNAVAILABLE = auto()
    EPS_ZERO = auto()
    EPS_NEGATIVE = auto()
    INVALID_PRICE = auto()

    @property
    def label(self) -> str:
        return PE_NOT_APPLICABLE_LABELS[self]


PE_NOT_APPLICABLE_LABELS = {
    PeNotApplicableReason.EPS_UNAVAILABLE: "資料不足",
    PeNotApplicableReason.EPS_ZERO: "無法計算",
    PeNotApplicableReason.EPS_NEGATIVE: "虧損，本益比不適用",
    PeNotApplicableReason.INVALID_PRICE: "無有效股價",
}


@invariant(lambda self: math.isfinite(self.price) and self.price > 0)
@invariant(lambda self: math.isfinite(self.eps) and self.eps > 0)
@dataclass(frozen=True)
class PeRatio:
    """A computable P/E. Holding a positive price and EPS makes it the only input a fair price accepts."""

    price: float
    eps: float

    @property
    def value(self) -> float:
        return self.price / self.eps


@dataclass(frozen=True)
class PeNotApplicable:
    reason: PeNotApplicableReason


type PeOutcome = PeRatio | PeNotApplicable


@dataclass(frozen=True)
class TargetPe:
    """The user's P/E assumption for one run. It is never persisted."""

    value: float

    def __post_init__(self) -> None:
        if not math.isfinite(self.value) or self.value <= 0:
            raise ValueError("目標本益比必須是大於 0 的有限數字")


class ScenarioName(StrEnum):
    CONSERVATIVE = auto()
    BASE = auto()
    OPTIMISTIC = auto()

    @property
    def label(self) -> str:
        return {ScenarioName.CONSERVATIVE: "保守", ScenarioName.BASE: "基準", ScenarioName.OPTIMISTIC: "樂觀"}[self]


@invariant(lambda self: math.isfinite(self.target_pe) and self.target_pe > 0)
@dataclass(frozen=True)
class ValuationScenario:
    name: ScenarioName
    target_pe: float
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

    @classmethod
    @require(lambda spread: 0 < spread < 1)
    def of(cls, pe: PeRatio, target: TargetPe, spread: float) -> FairPriceRange:
        def around_base(name: ScenarioName, factor: float, sign: str) -> ValuationScenario:
            assumption = f"基準 × (1 {sign} {spread:.0%})，依設定 valuation.scenario_spread"
            return ValuationScenario(name=name, target_pe=target.value * factor, assumption=assumption, pe=pe)

        return cls(
            conservative=around_base(ScenarioName.CONSERVATIVE, 1 - spread, "−"),
            base=ValuationScenario(name=ScenarioName.BASE, target_pe=target.value, assumption="使用者輸入的目標本益比", pe=pe),
            optimistic=around_base(ScenarioName.OPTIMISTIC, 1 + spread, "+"),
        )

    def __iter__(self) -> Iterator[ValuationScenario]:
        return iter((self.conservative, self.base, self.optimistic))


@dataclass(frozen=True)
class StockValuation:
    """
    One stock's valuation inputs before any user assumption: its EPS and the exchange's latest official close.

    EPS is read through the stock, whose only writer is FundamentalsFeed. P/E, freshness and warnings are derived.
    """

    stock: Stock
    close: Ohlcv | None
    last_closed_session: date

    @property
    def eps(self) -> Eps | EpsUnavailable:
        return self.stock.eps

    @property
    def close_is_fresh(self) -> bool:
        return self.close is not None and DailyCloseFreshnessRule().is_fresh(self.close.ts.date(), self.last_closed_session)

    @property
    def current_pe(self) -> PeOutcome:
        eps = self.eps

        if isinstance(eps, EpsUnavailable):
            return PeNotApplicable(PeNotApplicableReason.EPS_UNAVAILABLE)

        if eps.value == 0:
            return PeNotApplicable(PeNotApplicableReason.EPS_ZERO)

        if eps.value < 0:
            return PeNotApplicable(PeNotApplicableReason.EPS_NEGATIVE)

        if self.close is None or not math.isfinite(self.close.close) or self.close.close <= 0:
            return PeNotApplicable(PeNotApplicableReason.INVALID_PRICE)

        return PeRatio(price=self.close.close, eps=eps.value)

    @property
    def price_text(self) -> str:
        if self.close is None:
            return "無有效收盤價"

        return f"{self.close.close:,.2f} 元（{self.close.ts:%Y-%m-%d} 收盤，交易所公告）"

    @property
    def pe_text(self) -> str:
        match self.current_pe:
            case PeRatio() as pe:
                return f"{pe.value:.2f} 倍"
            case PeNotApplicable(reason=reason):
                return reason.label

    @property
    def warnings(self) -> tuple[str, ...]:
        warnings: list[str] = []
        eps = self.eps

        if isinstance(eps, EpsUnavailable):
            warnings.append(eps.describe())
        else:
            warnings.extend(
                f"{quarter} 財報尚未納入（申報期限 {quarter.filing_deadline}；公司尚未申報或資料未能取得），"
                f"本次使用至 {eps.period_end} 的近四季 EPS"
                for quarter in eps.newer_quarters
            )

            if eps.value == 0:
                warnings.append("近四季 EPS 為 0，無法計算本益比，不使用本益比估值")
            elif eps.value < 0:
                warnings.append(f"近四季 EPS 為 {eps.value:.2f}（虧損），本益比不適用，不計算合理價")

        if self.close is None:
            warnings.append("無有效收盤價：最近交易日無成交或交易所資料缺漏")
        elif not self.close_is_fresh:
            session = self.close.ts.date()
            missed = DailyCloseFreshnessRule().missed_sessions(session, self.last_closed_session)
            warnings.append(f"股價過期：收盤日 {session}，其後已有 {missed} 個交易日收盤（最近收盤交易日 {self.last_closed_session}）")

        return tuple(warnings)


@dataclass(frozen=True)
class ReportSection:
    title: str
    lines: tuple[str, ...]


@dataclass(frozen=True)
class ValuationReport:
    """A stock valued at the user's target P/E. Scenarios exist exactly when the current P/E is computable."""

    valuation: StockValuation
    target_pe: TargetPe | None
    fair_value: FairPriceRange | PeNotApplicable

    @classmethod
    def appraise(cls, valuation: StockValuation, target_pe: TargetPe | None, spread: float) -> ValuationReport:
        match valuation.current_pe:
            case PeNotApplicable() as not_applicable:
                return cls(valuation=valuation, target_pe=target_pe, fair_value=not_applicable)
            case PeRatio() as pe:
                if target_pe is None:
                    raise ValueError("A computable P/E needs a target P/E")

                return cls(valuation=valuation, target_pe=target_pe, fair_value=FairPriceRange.of(pe, target_pe, spread))

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

    def fact_sections(self) -> tuple[ReportSection, ...]:
        """US-107 items 1 to 6. The AI prompt's facts and the printed report are these same strings."""
        valuation = self.valuation

        return (
            ReportSection("目前股價", (valuation.price_text,)),
            ReportSection("EPS 與財報期間", (valuation.eps.describe(),)),
            ReportSection("目前本益比", (valuation.pe_text,)),
            ReportSection("目標本益比", (self._target_text(),)),
            ReportSection(f"推算合理股價（{LABEL}）", self._fair_price_lines()),
            ReportSection("高估／低估幅度", self._gap_lines()),
        )

    def _target_text(self) -> str:
        if isinstance(self.fair_value, FairPriceRange):
            return f"{self.fair_value.base.target_pe:.2f} 倍（使用者輸入，只用於本次分析）"

        reason = self.fair_value.reason.label

        if self.target_pe is None:
            return f"未設定（{reason}）"

        return f"{self.target_pe.value:.2f} 倍（使用者輸入；本股{reason}，不套用）"

    def _fair_price_lines(self) -> tuple[str, ...]:
        if isinstance(self.fair_value, PeNotApplicable):
            return (f"不適用：{self.fair_value.reason.label}（EPS ≤ 0 或資料不足時不使用本益比模型）",)

        return tuple(
            f"{scenario.name.label} {scenario.fair_price:,.2f} 元｜本益比 {scenario.target_pe:.2f} 倍｜假設：{scenario.assumption}"
            for scenario in self.fair_value
        )

    def _gap_lines(self) -> tuple[str, ...]:
        if isinstance(self.fair_value, PeNotApplicable):
            return ("不適用",)

        lines = [
            f"{scenario.name.label} 價差 {scenario.gap:+,.2f} 元，{_over_or_under(scenario.undervaluation)}"
            for scenario in self.fair_value
        ]

        return (*lines, UNDERVALUATION_FORMULA)


def _over_or_under(undervaluation: float) -> str:
    if undervaluation > 0:
        return f"低估 {undervaluation:.1%}"

    if undervaluation < 0:
        return f"高估 {-undervaluation:.1%}"

    return "股價等於合理價"


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
    def without_ai(cls, report: ValuationReport, reason: str) -> ValuationExplanation:
        return cls(report=report, higher_pe_factors=(), pe_derating_risks=(), data_gaps=(reason,), summary="", raw_response="")

    def sections(self) -> tuple[ReportSection, ...]:
        """Every US-107 item, in order, in every case: EPS missing, EPS ≤ 0, AI failed."""
        report = self.report
        risks = self.pe_derating_risks or (AI_NOT_PROVIDED,)

        if report.appears_undervalued:
            risks = (*risks, LOW_PE_CAVEAT)

        warnings = list(report.valuation.warnings)

        if not report.stock.articles:
            warnings.append("未取得相關新聞，AI 解釋僅依據估值數字")

        warnings.extend(f"AI：{gap}" for gap in self.data_gaps)

        return (
            *report.fact_sections(),
            ReportSection("可能支持較高本益比的因素", self.higher_pe_factors or (AI_NOT_PROVIDED,)),
            ReportSection("可能導致本益比下修的風險", risks),
            ReportSection("資料不足警告", tuple(warnings) or ("無",)),
            ReportSection("非投資建議聲明", (NOT_INVESTMENT_ADVICE,)),
            ReportSection("AI 摘要", (self.summary or AI_NOT_PROVIDED,)),
        )
