from dataclasses import dataclass

from icontract import invariant


@invariant(lambda self: 0 <= self.score <= 100, "AI score must be 0-100")
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
