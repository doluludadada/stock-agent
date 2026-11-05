from collections.abc import Iterator
from math import isfinite
from typing import Annotated, Literal, Self

from pydantic import ConfigDict, Field, FiniteFloat, Strict, model_validator
from pydantic.dataclasses import dataclass

from a_domain.model.market.ohlcv import Ohlcv
from a_domain.types.enums import ArithmeticOperator, ComparisonOperator, FormulaNode, GroupOperator, IndicatorOutput, MarketField
from a_domain.types.values import BarsAgo, FormulaId


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
    def _reads_data(self) -> Self:
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


@dataclass(frozen=True)
class FormulaInputs:
    """
    What a formula reads for one stock: its completed daily bars, oldest first; its latest price; and each indicator
    output the formula reads, keyed by indicator id and bars ago. An output the history could not give is absent.
    """

    bars: tuple[Ohlcv, ...]
    latest_price: float | None
    indicators: dict[tuple[FormulaId, int], dict[IndicatorOutput, FiniteFloat]]


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


def condition_holds(condition: Condition, inputs: FormulaInputs) -> bool | None:
    """
    Whether the condition holds, or None when it reads an unavailable input. A group evaluates every condition it
    holds before it answers, so one condition's result never hides another condition's missing input.
    """
    match condition:
        case ConditionGroup(operator=operator, conditions=conditions):
            results = [condition_holds(part, inputs) for part in conditions]

            if None in results:
                return None

            return all(results) if operator == GroupOperator.ALL else any(results)
        case Comparison():
            return comparison_holds(condition, inputs)


def comparison_holds(comparison: Comparison, inputs: FormulaInputs) -> bool | None:
    left, right = numeric_value(comparison.left, inputs), numeric_value(comparison.right, inputs)

    if left is None or right is None:
        return None

    match comparison.operator:
        case ComparisonOperator.GT:
            return left > right
        case ComparisonOperator.GTE:
            return left >= right
        case ComparisonOperator.LT:
            return left < right
        case ComparisonOperator.LTE:
            return left <= right
        case ComparisonOperator.EQ:
            return left == right
        case ComparisonOperator.NE:
            return left != right
        case _:
            return crossing_holds(comparison, inputs, left, right)


def crossing_holds(comparison: Comparison, inputs: FormulaInputs, left: float, right: float) -> bool | None:
    earlier_left, earlier_right = numeric_value(comparison.left, inputs, 1), numeric_value(comparison.right, inputs, 1)

    if earlier_left is None or earlier_right is None:
        return None

    if comparison.operator == ComparisonOperator.CROSSES_ABOVE:
        return earlier_left <= earlier_right and left > right

    return earlier_left >= earlier_right and left < right


def numeric_value(expression: NumericExpression, inputs: FormulaInputs, shift: int = 0) -> float | None:
    """The expression `shift` daily bars back, or None when an input is unavailable or the result is not finite."""
    match expression:
        case MarketValue(field=field, bars_ago=bars_ago):
            return finite(market_value(inputs.bars[-1 - bars_ago - shift], field))
        case LatestPrice():
            return finite(inputs.latest_price)
        case IndicatorValue(indicator_id=indicator_id, output=output, bars_ago=bars_ago):
            return inputs.indicators.get((indicator_id, bars_ago + shift), {}).get(output)
        case Arithmetic(operator=operator, left=left, right=right):
            return arithmetic(operator, numeric_value(left, inputs, shift), numeric_value(right, inputs, shift))
        case _:
            return expression


def market_value(bar: Ohlcv, field: MarketField) -> float:
    match field:
        case MarketField.OPEN:
            return bar.open
        case MarketField.HIGH:
            return bar.high
        case MarketField.LOW:
            return bar.low
        case MarketField.CLOSE:
            return bar.close
        case MarketField.VOLUME:
            return float(bar.volume)


def finite(value: float | None) -> float | None:
    """A price or volume that is not a finite number, such as a NaN from a bad data row, is unavailable."""
    return value if value is not None and isfinite(value) else None


def arithmetic(operator: ArithmeticOperator, left: float | None, right: float | None) -> float | None:
    """None for an unavailable side, a division by zero or a result too large to be finite: none of them is a zero."""
    if left is None or right is None:
        return None

    match operator:
        case ArithmeticOperator.ADD:
            result = left + right
        case ArithmeticOperator.SUBTRACT:
            result = left - right
        case ArithmeticOperator.MULTIPLY:
            result = left * right
        case ArithmeticOperator.DIVIDE:
            result = left / right if right != 0 else None

    return finite(result)
