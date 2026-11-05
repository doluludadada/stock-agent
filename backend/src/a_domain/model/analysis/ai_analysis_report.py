from pydantic.dataclasses import dataclass

from a_domain.types.values import Score


@dataclass(frozen=True)
class AiAnalysisReport:
    """
    Structured output from the LLM.
    Value Object inside Stock.
    """

    score: Score[int]
    bullish_factors: list[str]
    bearish_factors: list[str]
    summary: str
    raw_response: str
