from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class TargetPe:
    """The user's P/E assumption for one run. It is never persisted."""

    value: float

    def __post_init__(self) -> None:
        if not math.isfinite(self.value) or self.value <= 0:
            raise ValueError("目標本益比必須是大於 0 的有限數字")
