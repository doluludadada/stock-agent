from __future__ import annotations

from dataclasses import dataclass

from a_domain.model.valuation.report_section import ReportSection
from a_domain.model.valuation.valuation_report import ValuationReport

NOT_INVESTMENT_ADVICE = (
    "本報告僅為基於指定本益比的估值試算與資料整理，不構成投資建議；估值結果取決於所設定的本益比假設，並非客觀真實價值。"
)


LOW_PE_CAVEAT = "低本益比可能反映獲利成長下降、一次性收益墊高 EPS 或市場與產業風險；低本益比本身不是買進訊號。"


AI_NOT_PROVIDED = "（AI 未提供）"


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
        """Every section of the valuation explanation, in order, in every case: EPS missing, EPS ≤ 0, AI failed."""
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
