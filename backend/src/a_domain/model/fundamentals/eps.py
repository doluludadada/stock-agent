from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime

from icontract import invariant

from a_domain.model.fundamentals.fiscal_quarter import FiscalQuarter
from a_domain.types.enums import EpsBasis, EpsKind, InformationSource


@invariant(lambda self: math.isfinite(self.value))
@dataclass(frozen=True)
class Eps:
    """An EPS figure that always carries its period, kind, basis, source and fetch time."""

    value: float
    kind: EpsKind
    period_end: FiscalQuarter
    basis: EpsBasis
    source: InformationSource
    fetched_at: datetime
    """When the period_end quarter was fetched. Older inputs are final filings."""

    newer_quarters: tuple[FiscalQuarter, ...] = ()
    """Newer candidate quarters this figure does not include: not filed yet by the company, or not fetched."""

    @property
    def period_start(self) -> FiscalQuarter:
        if self.kind == EpsKind.SINGLE_QUARTER:
            return self.period_end

        if self.kind == EpsKind.TRAILING_TWELVE_MONTHS:
            return self.period_end.previous().previous().previous()

        return FiscalQuarter(self.period_end.year, 1)

    @property
    def period_label(self) -> str:
        if self.period_start == self.period_end:
            return str(self.period_end)

        return f"{self.period_start}–{self.period_end}"

    def describe(self) -> str:
        """The only text form of an EPS. It never shows the number without its period."""
        return (
            f"{self.value:,.2f} 元（{self.kind.label}，{self.period_label}，{self.basis.label}，"
            f"{SOURCE_LABELS[self.source]}，取得 {self.fetched_at:%Y-%m-%d %H:%M}）"
        )


SOURCE_LABELS = {InformationSource.TWSE_MOPS: "公開資訊觀測站"}
