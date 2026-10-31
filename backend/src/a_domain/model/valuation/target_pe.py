from __future__ import annotations

import math
from dataclasses import dataclass

TARGET_PE_REQUIREMENT = "The target P/E must be a finite number greater than 0"


@dataclass(frozen=True)
class TargetPe:
    """The user's P/E assumption for one run. It is never persisted."""

    value: float

    def __post_init__(self) -> None:
        if not math.isfinite(self.value) or self.value <= 0:
            raise ValueError(TARGET_PE_REQUIREMENT)
