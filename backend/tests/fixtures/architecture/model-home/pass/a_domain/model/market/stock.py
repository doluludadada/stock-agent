from pydantic.dataclasses import dataclass

from a_domain.model.analysis.ai_report import AiReport


@dataclass
class Stock:
    stock_id: str
    ai_report: AiReport | None = None
