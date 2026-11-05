from dataclasses import replace
from typing import Annotated, Self, override

from pydantic import Field
from pydantic.dataclasses import dataclass

type Score[Number: (int, float)] = Annotated[Number, Field(ge=0, le=100)]
"""A 0 to 100 scale, such as RSI or the technical score."""

type Fraction = Annotated[float, Field(ge=0, le=1)]

type ProperFraction = Annotated[float, Field(gt=0, lt=1)]
"""Strictly between 0 and 1, such as a stop-loss percentage or a scenario spread."""

type PositiveFiniteFloat = Annotated[float, Field(gt=0, allow_inf_nan=False)]

type NonNegativeFiniteFloat = Annotated[float, Field(ge=0, allow_inf_nan=False)]

type NonEmptyText = Annotated[str, Field(pattern=r"\S")]

type IndicatorPeriod = Annotated[int, Field(gt=0, le=500, strict=True)]
"""How many daily bars an indicator reads, such as an average's 20 or 60."""

type BarsAgo = Annotated[int, Field(ge=0, le=250, strict=True)]
"""Completed trading days before the latest daily bar: 0 is the latest bar, 1 the bar before it."""

type FormulaId = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,39}$")]
"""A stable identifier inside a strategy, such as a strategy's or an indicator's. It never holds a parameter."""


@dataclass(frozen=True, order=True)
class FiscalQuarter:
    """A calendar-year fiscal quarter in Gregorian years. The MOPS adapter converts ROC years."""

    year: int
    quarter: Annotated[int, Field(ge=1, le=4)]

    def previous(self) -> Self:
        if self.quarter == 1:
            return replace(self, year=self.year - 1, quarter=4)

        return replace(self, quarter=self.quarter - 1)

    @override
    def __str__(self) -> str:
        return f"{self.year}Q{self.quarter}"
