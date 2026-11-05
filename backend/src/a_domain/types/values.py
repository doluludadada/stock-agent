import unicodedata
from dataclasses import replace
from typing import Annotated, Self, override

from pydantic import AfterValidator, Field, SecretStr
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


type Username = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{2,31}$")]
"""3 to 32 characters and no '@', so a sign-in identifier is a username or an email and never both."""

type EmailAddress = Annotated[str, Field(max_length=254, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")]
"""The shape only. No mail is ever sent, so nothing proves the address is the user's."""

type NewPassword = Annotated[SecretStr, Field(min_length=12, max_length=256)]
"""A password a user chooses. SecretStr keeps it out of every repr and log line."""


def comparable_name(text: str) -> str:
    """
    A username or an email as sign-in compares it: NFKC-normalized, stripped and case-folded, so a full-width or
    upper-case "Alice " is "alice". The user store's unique indexes and the attempt limit per sign-in name compare
    names this way, and no other.
    """
    return unicodedata.normalize("NFKC", text).strip().casefold()


type SignInName = Annotated[str, AfterValidator(comparable_name)]
"""A username or an email as sign-in compares it."""


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
