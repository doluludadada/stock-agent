import json
from backend.src.a_domain.model.analysis.ai_sentiment import AiSentiment

class SentimentResponseParser:
    def parse(self, stock_id: str, raw_response: str) -> AiSentiment:
        fallback = AiSentiment(score=50, bullish_factors=[], bearish_factors=[], summary="Parse Error or Neutral", raw_response=raw_response)
        try:
            json_start = raw_response.find("{")
            json_end = raw_response.rfind("}") + 1
            if json_start == -1 or json_end == 0:
                return fallback
            parsed = json.loads(raw_response[json_start:json_end])
            def to_list(val):
                if isinstance(val, list): return [str(v) for v in val]
                if isinstance(val, str): return [x.strip() for x in val.split(",") if x.strip()]
                return []
            return AiSentiment(
                score=int(parsed.get("confidence_score", 50)),
                bullish_factors=to_list(parsed.get("bullish_factors", "")),
                bearish_factors=to_list(parsed.get("bearish_factors", "")),
                summary=f"AI Analysis for {stock_id}",
                raw_response=raw_response,
            )
        except (json.JSONDecodeError, ValueError):
            return fallback
