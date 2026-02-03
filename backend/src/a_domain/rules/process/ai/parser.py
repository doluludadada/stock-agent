import json

from backend.src.a_domain.model.analysis.ai_sentiment import AiSentiment


class SentimentResponseParser:
    """
    Rule: Parse the raw string response from AI into a structured AnalysisReport.
    """

    def parse(self, stock_id: str, raw_response: str) -> AiSentiment:
        # Default fallback
        fallback = AiSentiment(
            score=50,
            bullish_factors=[],
            bearish_factors=[],
            summary="Parse Error or Neutral",
            raw_response=raw_response,
        )

        try:
            json_start_index = raw_response.find("{")
            json_end_index = raw_response.rfind("}") + 1

            if json_start_index == -1 or json_end_index == 0:
                return fallback

            json_string = raw_response[json_start_index:json_end_index]
            parsed_data = json.loads(json_string)

            # Helper to convert comma-separated string to list
            def to_list(val: str | list) -> list[str]:
                if isinstance(val, list):
                    return [str(v) for v in val]
                if isinstance(val, str):
                    return [x.strip() for x in val.split(",") if x.strip()]
                return []

            return AiSentiment(
                score=int(parsed_data.get("confidence_score", 50)),
                bullish_factors=to_list(parsed_data.get("bullish_factors", "")),
                bearish_factors=to_list(parsed_data.get("bearish_factors", "")),
                summary=f"AI Analysis for {stock_id}",
                raw_response=raw_response,
            )

        except (json.JSONDecodeError, ValueError):
            return fallback


