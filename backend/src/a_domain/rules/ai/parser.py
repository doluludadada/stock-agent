import json
from dataclasses import dataclass

from a_domain.model.analysis.ai_analysis_report import AiAnalysisReport


# TODO:Clean here
@dataclass(frozen=True)
class AiReportParser:
    """
    Parses raw LLM output into AiAnalysisReport.

    This belongs to domain rules because it converts untrusted model output
    into a structured domain value object.
    """

    fallback_score: int = 50

    def parse(self, stock_id: str, raw_response: str) -> AiAnalysisReport:
        try:
            parsed = self._extract_json(raw_response)

            return AiAnalysisReport(
                score=int(parsed.get("confidence_score", self.fallback_score)),
                bullish_factors=self._to_list(parsed.get("bullish_factors")),
                bearish_factors=self._to_list(parsed.get("bearish_factors")),
                summary=str(parsed.get("summary", f"AI Analysis for {stock_id}")),
                raw_response=raw_response,
            )

        except (json.JSONDecodeError, ValueError, TypeError):
            return self._fallback(raw_response)

    def _extract_json(self, raw_response: str) -> dict:
        json_start = raw_response.find("{")
        json_end = raw_response.rfind("}") + 1

        if json_start == -1 or json_end <= 0:
            raise ValueError("No JSON object found in AI response.")

        parsed = json.loads(raw_response[json_start:json_end])

        if not isinstance(parsed, dict):
            raise ValueError("AI response JSON is not an object.")

        return parsed

    def _to_list(self, value) -> list[str]:
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]

        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]

        return []

    def _fallback(self, raw_response: str) -> AiAnalysisReport:
        return AiAnalysisReport(
            score=self.fallback_score,
            bullish_factors=[],
            bearish_factors=[],
            summary="Parse Error or Neutral",
            raw_response=raw_response,
        )
