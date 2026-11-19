from pydantic.dataclasses import dataclass

from a_domain.model.analysis.ai_report import AiReport


@dataclass(frozen=True)
class AiReportParser:
    max_score: int

    def apply(self, text: str) -> AiReport:
        return AiReport(score=min(len(text), self.max_score), summary=text)
