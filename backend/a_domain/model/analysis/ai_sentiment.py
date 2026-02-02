from dataclasses import dataclass


@dataclass
class AiSentiment:
    """
    Represents the structured output from the LLM.
    This is a Value Object inside AnalysisContext.
    """

    score: int  # 0-100
    bullish_factors: list[str]
    bearish_factors: list[str]
    summary: str
    raw_response: str
