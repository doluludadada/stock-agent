from datetime import datetime

from pydantic import ConfigDict, FiniteFloat
from pydantic.dataclasses import dataclass

from a_domain.types.enums import EpsBasis, EpsKind, EpsUnavailableReason, InformationSource
from a_domain.types.values import FiscalQuarter


@dataclass(frozen=True)
class Eps:
    """An EPS figure that always carries its period, kind, basis, source and fetch time."""

    value: FiniteFloat
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
            f"{self.value:,.2f} TWD ({self.kind.label}, {self.period_label}, {self.basis.label}, "
            f"{self.source.label}, fetched {self.fetched_at:%Y-%m-%d %H:%M})"
        )


@dataclass(frozen=True, config=ConfigDict(json_schema_serialization_defaults_required=True))
class EpsUnavailable:
    """Missing EPS. It is never 0, and the report shows "Insufficient data" with the reason."""

    reason: EpsUnavailableReason
    quarter: FiscalQuarter | None = None

    def describe(self) -> str:
        return f"Insufficient data: {self.reason.label.format(quarter=self.quarter)}"
