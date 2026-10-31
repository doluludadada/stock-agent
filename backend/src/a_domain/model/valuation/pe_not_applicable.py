from __future__ import annotations

from dataclasses import dataclass

from a_domain.types.enums import PeNotApplicableReason


@dataclass(frozen=True)
class PeNotApplicable:
    reason: PeNotApplicableReason
