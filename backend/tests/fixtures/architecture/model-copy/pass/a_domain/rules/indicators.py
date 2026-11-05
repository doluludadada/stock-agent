from pydantic.dataclasses import dataclass


@dataclass(frozen=True)
class MovingAverage:
    kind: str
    period: int


@dataclass(frozen=True)
class Momentum:
    kind: str
    period: int
