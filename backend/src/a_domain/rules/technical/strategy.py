from collections.abc import Sequence
from typing import Annotated, Self

import numpy as np
from pydantic import ConfigDict, Field, NonNegativeInt, model_validator
from pydantic.dataclasses import dataclass

from a_domain.model.analysis.technical_report import TechnicalObservation, TechnicalReport
from a_domain.model.market.ohlcv import Ohlcv
from a_domain.model.market.stock import Stock
from a_domain.rules.technical.calculation.calculator import IndicatorParameters, indicator_outputs, stacked_bars
from a_domain.rules.technical.formula import (
    Condition,
    DataReference,
    IndicatorValue,
    MarketValue,
    WindowInputs,
    condition_holds,
    references,
)
from a_domain.types.enums import MarketField, RuleEffect
from a_domain.types.values import Flags, Floats, FormulaId, Integers, NonEmptyText, Score


@dataclass(frozen=True, config=ConfigDict(extra="forbid"))
class TechnicalRule:
    """A condition and what passing or failing it does to the score. The name is a label: the condition alone decides."""

    name: NonEmptyText
    effect: RuleEffect
    condition: Condition


@dataclass(frozen=True, config=ConfigDict(extra="forbid"))
class TechnicalScoring:
    """
    Each rule's effect applies once, however many conditions it holds: a failed block_on_fail rule rejects the stock
    and costs block_failure_penalty, a failed reduce_score_on_fail rule costs failure_score_reduction, and a passed
    increase_score_on_pass rule adds pass_score_increase. Passing a block_on_fail rule adds nothing.
    """

    base_score: Score[int] = 50
    block_failure_penalty: NonNegativeInt = 15
    failure_score_reduction: NonNegativeInt = 5
    pass_score_increase: NonNegativeInt = 5

    def apply(self, rules: Sequence[TechnicalRule], passed: Sequence[bool]) -> TechnicalReport:
        hard_failures: list[str] = []
        soft_failures: list[str] = []
        observations: list[TechnicalObservation] = []
        score = self.base_score

        for rule, rule_passed in zip(rules, passed, strict=True):
            match rule.effect:
                case RuleEffect.BLOCK_ON_FAIL if not rule_passed:
                    hard_failures.append(rule.name)
                    score -= self.block_failure_penalty
                case RuleEffect.REDUCE_SCORE_ON_FAIL if not rule_passed:
                    soft_failures.append(rule.name)
                    score -= self.failure_score_reduction
                case RuleEffect.INCREASE_SCORE_ON_PASS:
                    observations.append(TechnicalObservation(rule=rule.name, detected=rule_passed))
                    score += self.pass_score_increase if rule_passed else 0

        return TechnicalReport(
            score=max(0, min(100, score)), hard_failures=hard_failures, soft_failures=soft_failures, observations=observations
        )


def bars_needed(reference: DataReference, shift: int, indicators: dict[FormulaId, IndicatorParameters]) -> int:
    match reference:
        case IndicatorValue(indicator_id=indicator_id, bars_ago=bars_ago):
            return indicators[indicator_id].required_bars + bars_ago + shift
        case MarketValue(bars_ago=bars_ago):
            return bars_ago + shift + 1
        case _:
            return 1


@dataclass(frozen=True, config=ConfigDict(extra="forbid"))
class TechnicalStrategy:
    """
    The user's formulas over named indicators, scored together. strategy_id is a stable key and name a label. An
    indicator id such as ind_a never holds a parameter: changing ind_a's period changes every rule that reads ind_a,
    and a rule that needs a different period reads another indicator.
    """

    strategy_id: FormulaId
    name: NonEmptyText
    indicators: dict[FormulaId, IndicatorParameters]
    scoring: TechnicalScoring
    rules: Annotated[tuple[TechnicalRule, ...], Field(min_length=1, max_length=100)]

    @model_validator(mode="after")
    def indicator_references_exist(self) -> Self:
        for rule in self.rules:
            for reference, _ in references(rule.condition):
                if not isinstance(reference, IndicatorValue):
                    continue

                parameters = self.indicators.get(reference.indicator_id)

                if parameters is None:
                    raise ValueError(
                        f"rule {rule.name!r} reads indicator {reference.indicator_id}, which the strategy does not define"
                    )

                if reference.output not in parameters.kind.outputs:
                    outputs = ", ".join(parameters.kind.outputs)
                    raise ValueError(
                        f"rule {rule.name!r} reads {reference.output} of {reference.indicator_id}; a {parameters.kind} gives {outputs}"
                    )

        return self

    @property
    def required_bars(self) -> int:
        """The completed daily bars the rules need: each reference's own history plus how far back it is read."""
        needs = (
            bars_needed(reference, shift, self.indicators) for rule in self.rules for reference, shift in references(rule.condition)
        )
        return max(needs, default=1)

    def apply(self, stocks: Sequence[Stock]) -> list[TechnicalReport]:
        """
        Each stock's report on its daily bars and latest price, in order. A stock with fewer daily bars than
        required_bars, or whose formulas read an unavailable input, divide by zero or reach a number too large to be
        finite, fails with score 0: no rule's result stands in for missing data.
        """
        required_bars = self.required_bars
        histories = [sorted(stock.ohlcv, key=lambda bar: bar.ts) for stock in stocks]
        scored = [(stock, bars) for stock, bars in zip(stocks, histories, strict=True) if len(bars) >= required_bars]
        reports = iter(window_reports(self, scored))
        return [
            next(reports)
            if len(bars) >= required_bars
            else TechnicalReport(score=0, hard_failures=[f"Need {required_bars} daily bars; received {len(bars)}"])
            for bars in histories
        ]


@dataclass(frozen=True, config=ConfigDict(extra="forbid"))
class TechnicalSettings:
    """
    One owner's strategies and the active one, which every workflow uses. revision counts the owner's saves, so a save
    from an older read is refused instead of overwriting.
    """

    active_strategy_id: FormulaId
    strategies: Annotated[tuple[TechnicalStrategy, ...], Field(min_length=1, max_length=50)]
    revision: NonNegativeInt = 0

    @model_validator(mode="after")
    def selects_its_own_strategies(self) -> Self:
        strategy_ids = {strategy.strategy_id for strategy in self.strategies}

        if len(strategy_ids) != len(self.strategies):
            raise ValueError("every strategy needs its own strategy_id")

        if self.active_strategy_id not in strategy_ids:
            raise ValueError(f"the selected strategy {self.active_strategy_id} is not one of the strategies")

        return self

    @property
    def active_strategy(self) -> TechnicalStrategy:
        return next(strategy for strategy in self.strategies if strategy.strategy_id == self.active_strategy_id)


def window_reports(strategy: TechnicalStrategy, scored: Sequence[tuple[Stock, Sequence[Ohlcv]]]) -> list[TechnicalReport]:
    """Each stock's report, its sorted daily bars one window of one matrix call; each holds at least required_bars."""
    if not scored:
        return []

    lengths = np.array([len(bars) for _, bars in scored], dtype=np.int64)
    prices = np.array([np.nan if stock.current_price is None else stock.current_price for stock, _ in scored], dtype=np.float64)
    results = rule_results(
        strategy, stacked_bars([bar for _, bars in scored for bar in bars]), np.cumsum(lengths) - 1, lengths, prices
    )
    return [
        rules_report(strategy, [(holds[window], available[window]) for holds, available in results]) for window in range(len(scored))
    ]


def rules_report(strategy: TechnicalStrategy, results: Sequence[tuple[np.bool_, np.bool_]]) -> TechnicalReport:
    """The strategy's report on one window from whether each rule holds there and whether its inputs are available."""
    unavailable = [rule.name for rule, (_, available) in zip(strategy.rules, results, strict=True) if not available]

    if unavailable:
        return TechnicalReport(score=0, hard_failures=[f"Technical data unavailable: {', '.join(unavailable)}"])

    return strategy.scoring.apply(strategy.rules, [bool(holds) for holds, _ in results])


def rule_results(
    strategy: TechnicalStrategy, bars: dict[MarketField, Floats], ends: Integers, lengths: Integers, latest_price: Floats
) -> list[tuple[Flags, Flags]]:
    """
    Where each rule holds, and where every input it reads is available, in each window: window `i` is the `lengths[i]`
    stacked bars up to `ends[i]`, with `latest_price[i]` as its latest price.
    """
    first = int((ends - lengths).min()) + 1
    span = {field: values[first : int(ends.max()) + 1] for field, values in bars.items()}
    latest = ends - first

    with np.errstate(all="ignore"):
        windows = np.minimum(latest - lengths + 1 + np.arange(int(lengths.max()))[:, None], len(span[MarketField.CLOSE]) - 1)
        indicators = {
            (indicator_id, bars_ago): outputs
            for indicator_id, reads in indicator_shifts(strategy.rules).items()
            for bars_ago, outputs in indicator_outputs(
                strategy.indicators[indicator_id], span, windows, latest, lengths, reads
            ).items()
        }
        inputs = WindowInputs(bars=span, ends=latest, latest_price=latest_price, indicators=indicators)
        return [condition_holds(rule.condition, inputs) for rule in strategy.rules]


def indicator_shifts(rules: Sequence[TechnicalRule]) -> dict[FormulaId, set[int]]:
    """How many bars back the rules read each indicator."""
    shifts: dict[FormulaId, set[int]] = {}

    for rule in rules:
        for reference, shift in references(rule.condition):
            if isinstance(reference, IndicatorValue):
                shifts.setdefault(reference.indicator_id, set()).add(reference.bars_ago + shift)

    return shifts
