from dataclasses import dataclass


@dataclass
class AiAnalysisReport:
    """
    Structured output from the LLM.
    Value Object inside Stock.
    """

    score: int  # 0-100
    bullish_factors: list[str]
    bearish_factors: list[str]
    summary: str
    raw_response: str
