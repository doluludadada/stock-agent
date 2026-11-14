from pydantic.dataclasses import dataclass


@dataclass(frozen=True)
class AttemptLimitRule:
    attempts: int

    def apply(self, earlier: int) -> bool:
        return earlier < self.attempts
