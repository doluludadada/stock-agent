import json

from src.a_domain.model.analysis.analysis_report import AnalysisReport


class SentimentResponseParser:
    """
    Rule: Parse the raw string response from AI into a structured AnalysisReport.
    Pure domain logic: Validates and converts JSON.
    """

    def parse(self, stock_id: str, raw_response: str) -> AnalysisReport:
        try:
            json_start_index = raw_response.find("{")
            json_end_index = raw_response.rfind("}") + 1

            if json_start_index == -1 or json_end_index == 0:
                raise ValueError("No JSON object found in response")

            json_string = raw_response[json_start_index:json_end_index]
            parsed_data = json.loads(json_string)

            return AnalysisReport(
                stock_id=stock_id,
                confidence_score=int(parsed_data.get("confidence_score", 50)),
                bullish_factors=str(parsed_data.get("bullish_factors", "")),
                bearish_factors=str(parsed_data.get("bearish_factors", "")),
                raw_llm_response=raw_response,
            )

        except (json.JSONDecodeError, ValueError):
            return AnalysisReport(
                stock_id=stock_id,
                confidence_score=50,
                bullish_factors="Parse error",
                bearish_factors="Parse error",
                raw_llm_response=raw_response,
            )
