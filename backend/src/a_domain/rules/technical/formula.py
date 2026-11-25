from collections.abc import Iterator
from functools import reduce
from typing import Annotated, Literal, Self

import numpy as np
from pydantic import ConfigDict, Field, Strict, model_validator
from pydantic.dataclasses import dataclass

from a_domain.rules.technical.calculation.calculator import Outputs, finite
from a_domain.types.enums import ArithmeticOperator, ComparisonOperator, FormulaNode, GroupOperator, IndicatorOutput, MarketField
from a_domain.types.values import BarsAgo, Flags, Floats, FormulaId, Integers


@dataclass(frozen=True, kw_only=True, config=ConfigDict(extra="forbid"))
class MarketValue:
    """
    A field of one completed daily bar, `bars_ago` trading days before the latest one.
    `{"type": "market", "field": "volume", "bars_ago": 1}` is yesterday's volume in shares.
    """

    type: Literal[FormulaNode.MARKET] = FormulaNode.MARKET
    field: MarketField
    bars_ago: BarsAgo = 0


@dataclass(frozen=True, kw_only=True, config=ConfigDict(extra="forbid"))
class LatestPrice:
    """
    The latest price: the run's realtime quote when it has one, else the latest daily close. It has no earlier
    sample, so a crossing cannot read it; a crossing of daily closes reads `{"type": "market", "field": "close"}`.
    """

    type: Literal[FormulaNode.LATEST_PRICE] = FormulaNode.LATEST_PRICE


@dataclass(frozen=True, kw_only=True, config=ConfigDict(extra="forbid"))
class IndicatorValue:
    """
    One output of one of the strategy's indicators, `bars_ago` trading days before the latest daily bar.
    `{"type": "indicator", "indicator_id": "ind_b", "output": "signal"}` is the MACD signal line of indicator ind_b.
    """

    type: Literal[FormulaNode.INDICATOR] = FormulaNode.INDICATOR
    indicator_id: FormulaId
    output: IndicatorOutput = IndicatorOutput.VALUE
    bars_ago: BarsAgo = 0


@dataclass(frozen=True, kw_only=True, config=ConfigDict(extra="forbid"))
class Arithmetic:
    """
    Two numbers combined: `{"type": "arithmetic", "operator": "multiply", "left": <25-day average volume>,
    "right": 1.8}` is 1.8 times that average. Either side may be another arithmetic part.
    """

    type: Literal[FormulaNode.ARITHMETIC] = FormulaNode.ARITHMETIC
    operator: ArithmeticOperator
    left: NumericExpression
    right: NumericExpression


type Number = Annotated[float, Strict(), Field(allow_inf_nan=False)]
"""A constant, written in JSON as the number itself: 0.05, 1.8 or 20."""

type DataReference = MarketValue | LatestPrice | IndicatorValue

type NumericExpression = Number | Annotated[DataReference | Arithmetic, Field(discriminator="type")]


@dataclass(frozen=True, kw_only=True, config=ConfigDict(extra="forbid"))
class Comparison:
    """
    Two numbers compared. `crosses_above` and `crosses_below` read both sides at the latest daily bar and at the bar
    before it, so `left` crossing above `right` holds only on the bar where it happened.
    """

    type: Literal[FormulaNode.COMPARISON] = FormulaNode.COMPARISON
    operator: ComparisonOperator
    left: NumericExpression
    right: NumericExpression

    @model_validator(mode="after")
    def reads_data(self) -> Self:
        if not any(True for _ in references(self)):
            raise ValueError("a comparison needs a side that reads market or indicator data")

        if self.operator.is_crossing and any(isinstance(reference, LatestPrice) for reference, _ in references(self)):
            raise ValueError("the latest price has no earlier sample, so a crossing compares daily values")

        return self


@dataclass(frozen=True, kw_only=True, config=ConfigDict(extra="forbid"))
class ConditionGroup:
    """`all` holds when every condition holds, `any` when at least one does. A group may hold other groups."""

    type: Literal[FormulaNode.GROUP] = FormulaNode.GROUP
    operator: GroupOperator
    conditions: Annotated[tuple[Condition, ...], Field(min_length=1, max_length=50)]


type Condition = Annotated[Comparison | ConditionGroup, Field(discriminator="type")]


def references(node: Condition | NumericExpression, shift: int = 0) -> Iterator[tuple[DataReference, int]]:
    """
    Every data reference in the formula, with how many more bars back it is read than its own bars_ago: a crossing
    reads each of its sides at the latest bar (0) and one bar earlier (1).
    """
    match node:
        case Comparison(operator=operator, left=left, right=right):
            for extra in (0, 1) if operator.is_crossing else (0,):
                yield from references(left, shift + extra)
                yield from references(right, shift + extra)
        case ConditionGroup(conditions=conditions):
            for condition in conditions:
                yield from references(condition, shift)
        case Arithmetic(left=left, right=right):
            yield from references(left, shift)
            yield from references(right, shift)
        case MarketValue() | LatestPrice() | IndicatorValue():
            yield node, shift
        case _:
            return


@dataclass(frozen=True, config=ConfigDict(arbitrary_types_allowed=True))
class WindowInputs:
    """
    What the formulas read for a batch of windows, each a stock's daily bars up to one session: the stacked bars the
    batch reaches, oldest first; the index there of each window's latest bar; each window's latest price; and each
    indicator output the formulas read, keyed by indicator id and bars ago. NaN stands for an input the window cannot give.
    """

    bars: dict[MarketField, Floats]
    ends: Integers
    latest_price: Floats
    indicators: dict[tuple[FormulaId, int], Outputs]


def condition_holds(condition: Condition, inputs: WindowInputs) -> tuple[Flags, Flags]:
    """
    Where the condition holds, and where every input it reads is available. A group is available only where every
    condition it holds is, so one condition's result never hides another condition's missing input.
    """
    match condition:
        case ConditionGroup(operator=operator, conditions=conditions):
            results = [condition_holds(part, inputs) for part in conditions]
            combine = np.logical_and if operator == GroupOperator.ALL else np.logical_or
            return reduce(combine, (holds for holds, _ in results)), reduce(np.logical_and, (available for _, available in results))
        case Comparison():
            return comparison_holds(condition, inputs)


def comparison_holds(comparison: Comparison, inputs: WindowInputs) -> tuple[Flags, Flags]:
    left, right = numeric_value(comparison.left, inputs), numeric_value(comparison.right, inputs)
    available = ~np.isnan(left) & ~np.isnan(right)

    match comparison.operator:
        case ComparisonOperator.GT:
            return left > right, available
        case ComparisonOperator.GTE:
            return left >= right, available
        case ComparisonOperator.LT:
            return left < right, available
        case ComparisonOperator.LTE:
            return left <= right, available
        case ComparisonOperator.EQ:
            return left == right, available
        case ComparisonOperator.NE:
            return left != right, available
        case _:
            return crossing_holds(comparison, inputs, left, right)


def crossing_holds(comparison: Comparison, inputs: WindowInputs, left: Floats, right: Floats) -> tuple[Flags, Flags]:
    earlier_left, earlier_right = numeric_value(comparison.left, inputs, 1), numeric_value(comparison.right, inputs, 1)
    available = ~np.isnan(left) & ~np.isnan(right) & ~np.isnan(earlier_left) & ~np.isnan(earlier_right)

    if comparison.operator == ComparisonOperator.CROSSES_ABOVE:
        return (earlier_left <= earlier_right) & (left > right), available

    return (earlier_left >= earlier_right) & (left < right), available


def numeric_value(expression: NumericExpression, inputs: WindowInputs, shift: int = 0) -> Floats:
    """The expression `shift` daily bars back in each window, NaN where an input is unavailable or the result is not finite."""
    match expression:
        case MarketValue(field=field, bars_ago=bars_ago):
            return finite(inputs.bars[field][inputs.ends - bars_ago - shift])
        case LatestPrice():
            return finite(inputs.latest_price)
        case IndicatorValue(indicator_id=indicator_id, output=output, bars_ago=bars_ago):
            return inputs.indicators[(indicator_id, bars_ago + shift)][output]
        case Arithmetic(operator=operator, left=left, right=right):
            return arithmetic(operator, numeric_value(left, inputs, shift), numeric_value(right, inputs, shift))
        case _:
            return np.full(len(inputs.ends), float(expression))


def arithmetic(operator: ArithmeticOperator, left: Floats, right: Floats) -> Floats:
    """NaN for an unavailable side, a division by zero or a result too large to be finite: none of them is a zero."""
    match operator:
        case ArithmeticOperator.ADD:
            result = left + right
        case ArithmeticOperator.SUBTRACT:
            result = left - right
        case ArithmeticOperator.MULTIPLY:
            result = left * right
        case ArithmeticOperator.DIVIDE:
            result = np.where(right != 0, left / right, np.nan)

    return finite(result)
