from dataclasses import dataclass

from a_domain.model.fundamentals.quarter_eps import EpsFilings


@dataclass(frozen=True)
class FilingWarningRule:
    """One warning per quarter whose filings could not be fetched or whose refresh failed, oldest quarter first."""

    def apply(self, filings: EpsFilings) -> tuple[str, ...]:
        warnings: list[str] = []

        for quarter in sorted(filings):
            filing = filings[quarter]

            if filing is None:
                warnings.append(
                    f"MOPS {quarter} filings could not be fetched; the EPS of a stock that needs this quarter shows insufficient data "
                    "or comes from an older quarter"
                )
                continue

            if filing.refresh_failed:
                warnings.append(
                    f"MOPS {quarter} filings could not be refreshed, so the data fetched at {filing.fetched_at:%Y-%m-%d %H:%M} "
                    "is used; the EPS of a company that filed after that shows insufficient data or comes from an older quarter"
                )

        return tuple(warnings)
