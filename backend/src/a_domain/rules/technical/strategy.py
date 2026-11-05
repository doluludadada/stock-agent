from collections.abc import Sequence
from typing import Annotated, Self

from pydantic import ConfigDict, Field, NonNegativeInt, model_validator
from pydantic.dataclasses import dataclass

from a_domain.model.analysis.technical_report import TechnicalReport
from a_domain.model.market.stock import Stock
from a_domain.rules.technical.calculation.calculator import IndicatorParameters, indicator_outputs
from a_domain.rules.technical.formula import (
    Condition,
    DataReference,
    FormulaInputs,
    IndicatorValue,
    MarketValue,
    condition_holds,
    references,
)
from a_domain.types.enums import RuleEffect
from a_domain.types.values import FormulaId, NonEmptyText, Score


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
        observations: list[str] = []
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
                    observations.append(f"{rule.name}: {'detected' if rule_passed else 'not detected'}")
                    score += self.pass_score_increase if rule_passed else 0

        return TechnicalReport(
            score=max(0, min(100, score)), hard_failures=hard_failures, soft_failures=soft_failures, observations=observations
        )


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
    def _indicator_references_exist(self) -> Self:
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
        needs = (self._bars_needed(reference, shift) for rule in self.rules for reference, shift in references(rule.condition))
        return max(needs, default=1)

    def apply(self, stock: Stock) -> TechnicalReport:
        """
        A stock with fewer daily bars than required_bars, or whose formulas read an unavailable input, divide by zero
        or reach a number too large to be finite, fails with score 0: no rule's result stands in for missing data.
        """
        bars = tuple(sorted(stock.ohlcv, key=lambda bar: bar.ts))

        if len(bars) < self.required_bars:
            return TechnicalReport(score=0, hard_failures=[f"Need {self.required_bars} daily bars; received {len(bars)}"])

        read = {
            (reference.indicator_id, reference.bars_ago + shift)
            for rule in self.rules
            for reference, shift in references(rule.condition)
            if isinstance(reference, IndicatorValue)
        }
        outputs = {key: indicator_outputs(self.indicators[key[0]], bars[: len(bars) - key[1]]) for key in read}
        inputs = FormulaInputs(bars=bars, latest_price=stock.current_price, indicators=outputs)
        results = [condition_holds(rule.condition, inputs) for rule in self.rules]
        passed = [result for result in results if result is not None]

        if len(passed) < len(results):
            unavailable = ", ".join(rule.name for rule, result in zip(self.rules, results, strict=True) if result is None)
            return TechnicalReport(score=0, hard_failures=[f"Technical data unavailable: {unavailable}"])

        return self.scoring.apply(self.rules, passed)

    def _bars_needed(self, reference: DataReference, shift: int) -> int:
        match reference:
            case IndicatorValue(indicator_id=indicator_id, bars_ago=bars_ago):
                return self.indicators[indicator_id].required_bars + bars_ago + shift
            case MarketValue(bars_ago=bars_ago):
                return bars_ago + shift + 1
            case _:
                return 1


@dataclass(frozen=True, config=ConfigDict(extra="forbid"))
class TechnicalSettings:
    """
    One owner's strategies and which one each workflow uses: the Buzz strategy for Buzz, the active one for every
    other workflow. revision counts the owner's saves, so a save from an older read is refused instead of overwriting.
    """

    active_strategy_id: FormulaId
    buzz_strategy_id: FormulaId
    strategies: Annotated[tuple[TechnicalStrategy, ...], Field(min_length=1, max_length=50)]
    revision: NonNegativeInt = 0

    @model_validator(mode="after")
    def _selects_its_own_strategies(self) -> Self:
        strategy_ids = {strategy.strategy_id for strategy in self.strategies}

        if len(strategy_ids) != len(self.strategies):
            raise ValueError("every strategy needs its own strategy_id")

        for selected in (self.active_strategy_id, self.buzz_strategy_id):
            if selected not in strategy_ids:
                raise ValueError(f"the selected strategy {selected} is not one of the strategies")

        return self

    @property
    def active_strategy(self) -> TechnicalStrategy:
        return next(strategy for strategy in self.strategies if strategy.strategy_id == self.active_strategy_id)

    @property
    def buzz_strategy(self) -> TechnicalStrategy:
        return next(strategy for strategy in self.strategies if strategy.strategy_id == self.buzz_strategy_id)
