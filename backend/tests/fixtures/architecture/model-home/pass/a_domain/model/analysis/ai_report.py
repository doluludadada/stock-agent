from pydantic.dataclasses import dataclass


@dataclass(frozen=True)
class AiReport:
    score: int
    summary: str
