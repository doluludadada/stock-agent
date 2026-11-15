from typing import Annotated, Literal, Self

from pydantic import ConfigDict, Field, NonNegativeFloat, NonNegativeInt, PositiveInt, model_validator
from pydantic.dataclasses import dataclass

from a_domain.types.enums import RankingFactorKind
from a_domain.types.values import FormulaId


@dataclass(frozen=True, kw_only=True, config=ConfigDict(extra="forbid", use_attribute_docstrings=True))
class RevenueAcceleration:
    kind: Literal[RankingFactorKind.REVENUE_ACCELERATION] = RankingFactorKind.REVENUE_ACCELERATION
    short_months: PositiveInt
    long_months: PositiveInt

    @model_validator(mode="after")
    def the_short_months_are_among_the_long(self) -> Self:
        if self.short_months > self.long_months:
            raise ValueError("short_months must not be more than long_months")

        return self


@dataclass(frozen=True, kw_only=True, config=ConfigDict(extra="forbid", use_attribute_docstrings=True))
class RevenueYoy:
    kind: Literal[RankingFactorKind.REVENUE_YOY] = RankingFactorKind.REVENUE_YOY
    months: PositiveInt


@dataclass(frozen=True, kw_only=True, config=ConfigDict(extra="forbid", use_attribute_docstrings=True))
class NearnessToHigh:
    kind: Literal[RankingFactorKind.NEARNESS_TO_HIGH] = RankingFactorKind.NEARNESS_TO_HIGH
    high_sessions: PositiveInt
    """The sessions whose highest total-return level the level at the decision is compared with."""


@dataclass(frozen=True, kw_only=True, config=ConfigDict(extra="forbid", use_attribute_docstrings=True))
class PriceMomentum:
    kind: Literal[RankingFactorKind.PRICE_MOMENTUM] = RankingFactorKind.PRICE_MOMENTUM
    sessions: PositiveInt
    skip_sessions: NonNegativeInt
    """The latest sessions left out, so the newest move does not count."""

    @model_validator(mode="after")
    def the_skipped_sessions_are_among_the_sessions(self) -> Self:
        if self.skip_sessions >= self.sessions:
            raise ValueError("skip_sessions must be fewer than sessions")

        return self


type RankingFactor = Annotated[RevenueAcceleration | RevenueYoy | NearnessToHigh | PriceMomentum, Field(discriminator="kind")]
"""One measure of a stock, by its kind (RankingFactorKind) and the windows it reads."""


@dataclass(frozen=True, kw_only=True, config=ConfigDict(extra="forbid", use_attribute_docstrings=True))
class RankingFormula:
    """
    One way to make the monthly ranking, as the settings name it: the factors whose ranks it sums, the universe it
    ranks, how many of the best scores it holds, and when it holds cash instead. It is data alone: the one ranking rule,
    its backtest and a stock's standing all read it, and a run that followed a ranking keeps the formula it used.
    """

    name: FormulaId
    factors: tuple[RankingFactor, ...]
    """Each is ranked among the universe's stocks that have it, and a stock's score is the sum of its ranks."""

    top: PositiveInt
    """How many of the best scores it holds, in equal weights."""

    min_close: NonNegativeFloat
    min_traded_value: NonNegativeFloat
    traded_value_sessions: PositiveInt
    """
    The universe: the stocks (no ETF) that traded at the decision, closed at min_close or more, and traded
    min_traded_value NT$ a session on average over the last traded_value_sessions sessions.
    """

    cash_under_average_sessions: PositiveInt | None = None
    """
    The market filter: the formula holds cash for the month when the benchmark's total-return level at the decision's
    close is under its own average of this many sessions. None holds the ranking whatever the benchmark does.
    """

    @model_validator(mode="after")
    def the_formula_ranks_a_factor(self) -> Self:
        if not self.factors:
            raise ValueError("a formula needs at least one factor")

        return self
