from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ReportSection:
    title: str
    lines: tuple[str, ...]
