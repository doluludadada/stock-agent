import json
from dataclasses import replace

from pydantic import ValidationError

from a_domain.model.analysis.ai_analysis_report import AiAnalysisReport
from a_domain.model.market.article import Article
from a_domain.model.valuation.valuation import ValuationExplanation, ValuationReport
from a_domain.types.enums import SentimentLabel
from a_domain.types.errors import AiReportParseError


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

    refusal = f"confidence_score must be an integer from 0 to 100, got {score!r}."

    if isinstance(score, bool) or not isinstance(score, int):
        raise AiReportParseError(refusal)

    summary = parsed.get("summary")

    try:
        return AiAnalysisReport(
            score=score,
            bullish_factors=to_text_list(parsed.get("bullish_factors")),
            bearish_factors=to_text_list(parsed.get("bearish_factors")),
            summary=summary.strip() if isinstance(summary, str) else "",
            raw_response=raw_response,
        )
    except ValidationError as error:
        raise AiReportParseError(refusal) from error


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
            data_gaps=("The AI reply could not be read",),
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


def parse_sentiment_reply(raw_response: str, posts: list[Article]) -> list[Article]:
    """
    Reads each post's stance from the AI's reply, which numbers the posts from 1 in order, and returns a classified copy
    of each post the reply covers, in post order. An item with an unknown number, label or confidence is left out, and
    the first item for a post wins. Raises AiReportParseError when no item is usable.
    """
    items = extract_json_object(raw_response).get("posts")

    if not isinstance(items, list):
        raise AiReportParseError("Sentiment reply has no posts list.")

    classified: dict[int, Article] = {}

    for item in items:
        if (parsed := parse_sentiment_item(item, posts)) is not None:
            classified.setdefault(*parsed)

    if not classified:
        raise AiReportParseError("Sentiment reply has no usable post classification.")

    return [classified[number] for number in sorted(classified)]


def parse_sentiment_item(item: object, posts: list[Article]) -> tuple[int, Article] | None:
    if not isinstance(item, dict):
        return None

    index, label, confidence = item.get("index"), item.get("label"), item.get("confidence")

    if isinstance(index, bool) or not isinstance(index, int) or not 1 <= index <= len(posts):
        return None

    if not isinstance(label, str) or label.strip().lower() not in SentimentLabel:
        return None

    if isinstance(confidence, bool) or not isinstance(confidence, int | float):
        return None

    try:
        return index, replace(
            posts[index - 1], sentiment=SentimentLabel(label.strip().lower()), sentiment_confidence=float(confidence)
        )
    except ValidationError:
        return None
