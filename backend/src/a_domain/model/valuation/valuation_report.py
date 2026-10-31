from __future__ import annotations

from dataclasses import dataclass

from a_domain.model.market.stock import Stock
from a_domain.model.valuation.fair_price_range import FairPriceRange
from a_domain.model.valuation.pe_not_applicable import PeNotApplicable
from a_domain.model.valuation.pe_ratio import PeRatio
from a_domain.model.valuation.report_section import ReportSection
from a_domain.model.valuation.stock_valuation import StockValuation
from a_domain.model.valuation.target_pe import TargetPe
from a_domain.model.valuation.valuation_scenario import ValuationScenario

LABEL = "基於指定本益比的估值"


UNDERVALUATION_FORMULA = "低估幅度 = (合理價 − 目前股價) ÷ 目前股價；正值為低估，負值為高估"


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
        """Price, EPS, current and target P/E, fair prices and gaps: the AI prompt's facts and the printed report alike."""
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
