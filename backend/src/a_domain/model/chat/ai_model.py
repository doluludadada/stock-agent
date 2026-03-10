from dataclasses import dataclass

from a_domain.types.enums import AiProvider


@dataclass(frozen=True)
class AIModel:
    provider: AiProvider
    name: str
