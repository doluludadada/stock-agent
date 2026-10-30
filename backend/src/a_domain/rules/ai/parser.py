import json

from a_domain.model.analysis.ai_analysis_report import AiAnalysisReport
from a_domain.model.valuation.valuation import ValuationExplanation, ValuationReport


class AiReportParseError(ValueError):
    """The model response holds no usable report, so the stock gets no AI score."""


def parse_ai_report(raw_response: str) -> AiAnalysisReport:
    """
    Parses raw LLM output into AiAnalysisReport.

    The score must come from the model. A response without a valid 0-100 confidence_score
    raises AiReportParseError instead of falling back to a default score.
    """
    parsed = extract_json_object(raw_response)
    score = parsed.get("confidence_score")

    if isinstance(score, float) and score.is_integer():
        score = int(score)

    if isinstance(score, bool) or not isinstance(score, int) or not 0 <= score <= 100:
        raise AiReportParseError(f"confidence_score must be an integer from 0 to 100, got {score!r}.")

    summary = parsed.get("summary")

    return AiAnalysisReport(
        score=score,
        bullish_factors=to_text_list(parsed.get("bullish_factors")),
        bearish_factors=to_text_list(parsed.get("bearish_factors")),
        summary=summary.strip() if isinstance(summary, str) else "",
        raw_response=raw_response,
    )


def extract_json_object(raw_response: str) -> dict:
    json_start = raw_response.find("{")
    json_end = raw_response.rfind("}") + 1

    if json_start == -1 or json_end <= json_start:
        raise AiReportParseError("No JSON object found in the AI response.")

    try:
        return json.loads(raw_response[json_start:json_end])
    except json.JSONDecodeError as error:
        raise AiReportParseError(f"AI response JSON is malformed: {error}") from error


def to_text_list(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]

    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]

    return []


def parse_valuation_explanation(report: ValuationReport, raw_response: str) -> ValuationExplanation:
    """Reads only the text keys. Any other key, numeric or not, is ignored, so no number reaches the report from the AI."""
    try:
        parsed = extract_json_object(raw_response)
    except ValueError:
        return ValuationExplanation(
            report=report,
            higher_pe_factors=(),
            pe_derating_risks=(),
            data_gaps=("AI 回覆無法解析",),
            summary="",
            raw_response=raw_response,
        )

    summary = parsed.get("summary")

    return ValuationExplanation(
        report=report,
        higher_pe_factors=tuple(to_text_list(parsed.get("higher_pe_factors"))),
        pe_derating_risks=tuple(to_text_list(parsed.get("pe_derating_risks"))),
        data_gaps=tuple(to_text_list(parsed.get("data_gaps"))),
        summary=summary.strip() if isinstance(summary, str) else "",
        raw_response=raw_response,
    )
