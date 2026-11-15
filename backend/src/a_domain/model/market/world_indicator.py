from datetime import date

from pydantic import FiniteFloat, computed_field
from pydantic.dataclasses import dataclass

from a_domain.types.enums import WorldIndicator


@dataclass(frozen=True, kw_only=True)
class IndicatorReading:
    """
    One world indicator on one day, as its source served it, beside the reading the site holds of the day before it:
    a source serves the first alone, and the site's store answers both.
    """

    indicator: WorldIndicator
    day: date
    """The day the source dates the reading: a Taipei day for an exchange rate, a New York day for a Treasury yield."""

    value: FiniteFloat
    previous_day: date | None = None
    previous: FiniteFloat | None = None
    """The reading of the newest day held before `day`. None while the site holds no earlier one."""

    @computed_field
    @property
    def change(self) -> float | None:
        """
        How far it moved from the reading before: for an indicator in percent, the difference in percentage points
        (0.05 is five hundredths of a point more); for any other, the share of the reading before (0.012 is 1.2% more).
        None without a reading before, or one of 0.
        """
        if self.previous is None:
            return None

        if self.indicator.in_percent:
            return self.value - self.previous

        return self.value / self.previous - 1 if self.previous else None
