from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PeMedian:
    value: float
    sample_size: int
