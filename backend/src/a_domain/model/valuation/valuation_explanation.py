from __future__ import annotations

from dataclasses import dataclass

from a_domain.model.valuation.report_section import ReportSection
from a_domain.model.valuation.valuation_report import ValuationReport

NOT_INVESTMENT_ADVICE = (
    "This report is only a valuation estimate based on a specified P/E and a summary of the data. It is not investment "
    "advice. The result depends on the assumed P/E and is not an objective true value."
)


LOW_PE_CAVEAT = (
    "A low P/E can reflect falling earnings growth, one-off gains that inflate EPS, or market and industry risk; "
    "a low P/E alone is not a buy signal."
)


AI_NOT_PROVIDED = "(not provided by the AI)"


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
            warnings.append("No related news was found, so the AI explanation relies on the valuation numbers only")

        warnings.extend(f"AI: {gap}" for gap in self.data_gaps)

        return (
            *report.fact_sections(),
            ReportSection("Factors that may support a higher P/E", self.higher_pe_factors or (AI_NOT_PROVIDED,)),
            ReportSection("Risks that may lower the P/E", risks),
            ReportSection("Insufficient data warnings", tuple(warnings) or ("none",)),
            ReportSection("Not investment advice", (NOT_INVESTMENT_ADVICE,)),
            ReportSection("AI summary", (self.summary or AI_NOT_PROVIDED,)),
        )
