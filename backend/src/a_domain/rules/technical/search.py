from collections.abc import Callable, Iterator, Mapping, Sequence, Set
from dataclasses import fields, replace
from datetime import date, datetime
from functools import cache
from math import ceil
from random import Random
from typing import Annotated, Any, Self

from pydantic import Field, NonNegativeInt, PositiveInt, TypeAdapter, ValidationError, model_validator
from pydantic.dataclasses import dataclass

from a_domain.model.market.ohlcv import Ohlcv
from a_domain.model.trading.account import Account
from a_domain.model.trading.backtest import Backtest, BacktestInputs, BacktestTrade, SearchInputs
from a_domain.rules.technical.calculation.calculator import IndicatorParameters
from a_domain.rules.technical.formula import (
    Arithmetic,
    Comparison,
    Condition,
    ConditionGroup,
    IndicatorValue,
    MarketValue,
    NumericExpression,
    references,
)
from a_domain.rules.technical.matrix import DailyBarMatrix, StrategyScoresRule
from a_domain.rules.technical.strategy import TechnicalRule, TechnicalStrategy
from a_domain.rules.trading.backtest import BacktestRule
from a_domain.types.enums import (
    ArithmeticOperator,
    ComparisonOperator,
    FormulaScale,
    IndicatorKind,
    IndicatorOutput,
    MarketField,
    RuleEffect,
    SearchLevel,
    SearchSpan,
    StrategyMutation,
)
from a_domain.types.errors import BacktestPeriodUnavailable
from a_domain.types.values import (
    FormulaId,
    Fraction,
    IndicatorPeriod,
    NonNegativeFiniteFloat,
    PositiveFiniteFloat,
    ProperFraction,
    Score,
)


@dataclass(frozen=True, kw_only=True)
class StrategyCandidate:
    """
    What a strategy search tries: a strategy, valid as any saved one, and the scores a backtest of it buys at and sells
    at, which a run reads from analysis.min_combined_score_buy and analysis.max_combined_score_sell.
    """

    strategy: TechnicalStrategy
    buy_score: Score[int]
    sell_score: Score[int]

    @model_validator(mode="after")
    def _sells_below_the_buy_score(self) -> Self:
        if self.sell_score >= self.buy_score:
            raise ValueError("the sell score must be below the buy score")

        return self

    @property
    def key(self) -> str:
        """The candidate as JSON: two candidates with one key score and trade alike."""
        return candidate_json().dump_json(self).decode()


@dataclass(frozen=True, kw_only=True)
class SpanResult:
    """
    What a candidate's backtest over one span came to: Backtest's figures alone, since a search keeps thousands of
    them and ships each between processes, where whole backtests with the account at every session would not fit.
    """

    sessions: PositiveInt
    return_pct: Annotated[float, Field(ge=-1, allow_inf_nan=False)]
    max_drawdown_pct: Fraction
    trades: NonNegativeInt
    closed_trades: NonNegativeInt
    """The trades sold before the span's last session; the others are still held there."""


@dataclass(frozen=True)
class CandidateBacktestRule:
    """
    What candidates of one strategy came to over one span, each as a backtest of the strategy at the candidate's two
    scores reports it (BacktestReplay): the strategy's scores over `bars`, the history BacktestHistoryRule gives the
    span, computed once (StrategyScoresRule), then replayed from `first` on initial_cash by the BacktestRule of the
    candidate's buy and sell score in backtest_rules.
    """

    initial_cash: PositiveFiniteFloat
    stop_loss_pct: ProperFraction
    risk_per_trade_pct: Annotated[float, Field(gt=0, le=1)]

    def apply(
        self,
        bars: DailyBarMatrix,
        window_starts: Sequence[int],
        candidates: Sequence[StrategyCandidate],
        first: date,
        backtest_rules: Mapping[tuple[int, int], BacktestRule],
        session_close: Callable[[date], datetime],
    ) -> list[SpanResult]:
        scores = StrategyScoresRule(strategy=candidates[0].strategy).apply(bars, window_starts)
        results: list[SpanResult] = []

        for candidate in candidates:
            buy_score, sell_score = candidate.buy_score, candidate.sell_score
            inputs = BacktestInputs(
                first=first, last=bars.sessions[-1], initial_cash=self.initial_cash, buy_score=buy_score, sell_score=sell_score
            )
            curve, trades = backtest_rules[buy_score, sell_score].apply(bars, scores, {}, first, self.initial_cash, session_close)
            results.append(self._result(candidate, inputs, curve, trades, session_close(inputs.last)))

        return results

    def _result(
        self,
        candidate: StrategyCandidate,
        inputs: BacktestInputs,
        curve: dict[date, Account],
        trades: list[BacktestTrade],
        at: datetime,
    ) -> SpanResult:
        """The figures of the candidate's Backtest, built for them alone and stamped `at`, the span's last close."""
        backtest = Backtest(
            created_at=at,
            strategy_id=candidate.strategy.strategy_id,
            strategy_name=candidate.strategy.name,
            inputs=inputs,
            stop_loss_pct=self.stop_loss_pct,
            risk_per_trade_pct=self.risk_per_trade_pct,
            equity_curve=curve,
            benchmark=[],
            trades=trades,
        )

        return SpanResult(
            sessions=len(curve),
            return_pct=backtest.total_return_pct,
            max_drawdown_pct=backtest.max_drawdown_pct,
            trades=backtest.trade_count,
            closed_trades=sum(trade.sold_on is not None for trade in trades),
        )


@dataclass(frozen=True, kw_only=True)
class SearchHistory:
    """What a strategy search reads: every listed stock's daily bars, its spans over them, and when it began."""

    started_at: datetime
    bars: DailyBarMatrix
    spans: dict[SearchSpan, tuple[date, date]]


@dataclass(frozen=True, kw_only=True)
class SearchTrial:
    """A candidate a search backtested, and its result on each span it was backtested over."""

    candidate: StrategyCandidate
    results: dict[SearchSpan, SpanResult]


@dataclass(frozen=True)
class SearchFitnessRule:
    """
    How good a backtest over a span was: return_pct - drawdown_penalty x max_drawdown_pct, for one with at least
    min_trades_per_100_sessions closed trades per 100 sessions. One with fewer ranks below `floor`, under every one with
    enough, the higher the closer it came, so a handful of lucky trades never wins.
    """

    min_trades_per_100_sessions: NonNegativeFiniteFloat
    drawdown_penalty: NonNegativeFiniteFloat

    @property
    def floor(self) -> float:
        """The least fitness of a backtest with enough closed trades: everything lost, at a drawdown of 100%."""
        return -1 - self.drawdown_penalty

    def apply(self, result: SpanResult) -> float:
        required = ceil(self.min_trades_per_100_sessions * result.sessions / 100)

        if result.closed_trades < required:
            return self.floor - (required - result.closed_trades) / required

        return result.return_pct - self.drawdown_penalty * result.max_drawdown_pct


@dataclass(frozen=True)
class FittestRule:
    """The `count` trials of the highest fitness on `span`, highest first; of two as fit, the one tried first."""

    fitness_rule: SearchFitnessRule

    def apply(self, trials: Sequence[SearchTrial], span: SearchSpan, count: int) -> list[SearchTrial]:
        return sorted(trials, key=lambda trial: -self.fitness_rule.apply(trial.results[span]))[:count]


@dataclass(frozen=True)
class SessionSplitRule:
    """
    A search's spans: the sessions from `first` on in time order, the first train_share of them train, the next
    validation_share validation and the rest the holdout. No session is in two spans. A history too short for a
    session in each raises BacktestPeriodUnavailable.
    """

    train_share: ProperFraction
    validation_share: ProperFraction

    @model_validator(mode="after")
    def _leaves_a_holdout(self) -> Self:
        if self.train_share + self.validation_share >= 1:
            raise ValueError("train_share and validation_share must leave sessions for the holdout")

        return self

    def apply(self, sessions: Sequence[date], first: date) -> dict[SearchSpan, tuple[date, date]]:
        covered = [session for session in sessions if session >= first]
        train_end = round(len(covered) * self.train_share)
        validation_end = train_end + round(len(covered) * self.validation_share)

        if not 0 < train_end < validation_end < len(covered):
            raise BacktestPeriodUnavailable(
                f"A strategy search needs sessions for train, validation and the holdout; the history holds "
                f"{len(covered)} from {first}."
            )

        return {
            SearchSpan.TRAIN: (covered[0], covered[train_end - 1]),
            SearchSpan.VALIDATION: (covered[train_end], covered[validation_end - 1]),
            SearchSpan.HOLDOUT: (covered[validation_end], covered[-1]),
        }


@dataclass(frozen=True)
class LuckSampleRule:
    """
    The luck baseline's candidates: `count` of the trials with enough closed trades on train, drawn at random from
    `seed`, or all of them when fewer have. A winner whose holdout return beats few of theirs was picked by luck.
    """

    fitness_rule: SearchFitnessRule

    def apply(self, trials: Sequence[SearchTrial], count: int, seed: int) -> list[SearchTrial]:
        floor = self.fitness_rule.floor
        qualified = [trial for trial in trials if self.fitness_rule.apply(trial.results[SearchSpan.TRAIN]) >= floor]

        return Random(seed).sample(qualified, min(count, len(qualified)))


@dataclass(frozen=True)
class StrategyMutationRule:
    """
    One mutation of a candidate (StrategyMutation), drawn from `seed`. The result is a valid candidate whose strategy
    reads its indicators in id order, defines no indicator its rules do not read, needs at most max_required_bars daily
    bars and holds at most max_rules rules; or the candidate itself, when the mutation finds nothing to change or its
    change breaks one of those limits. `origin` is the strategy the search started from, whose rules RESTORE_RULE
    brings back. A generated condition reads a new indicator's period from `periods`, and compares a number with a level
    of its scale from `levels`.
    """

    period_step: ProperFraction
    constant_step: ProperFraction
    score_step: PositiveInt
    max_required_bars: PositiveInt
    max_rules: PositiveInt
    periods: Annotated[tuple[IndicatorPeriod, ...], Field(min_length=1)]
    levels: dict[FormulaScale, tuple[float, ...]]

    def apply(
        self, candidate: StrategyCandidate, mutation: StrategyMutation, origin: TechnicalStrategy, seed: int
    ) -> StrategyCandidate:
        try:
            changed = self._changed(candidate, mutation, origin, Random(seed))

            if changed is None:
                return candidate

            strategy = replace(changed.strategy, indicators=read_indicators(changed.strategy))
        except ValidationError:
            return candidate

        if strategy.required_bars > self.max_required_bars or len(strategy.rules) > self.max_rules:
            return candidate

        return replace(changed, strategy=strategy)

    def _changed(
        self, candidate: StrategyCandidate, mutation: StrategyMutation, origin: TechnicalStrategy, random: Random
    ) -> StrategyCandidate | None:
        strategy = candidate.strategy

        match mutation:
            case StrategyMutation.PERIOD:
                changed = tuned_period(strategy, self.period_step, random)
            case StrategyMutation.CONSTANT:
                changed = tuned_constant(strategy, self.constant_step, random)
            case StrategyMutation.SCORING:
                changed = tuned_scoring(strategy, self.score_step, random)
            case StrategyMutation.THRESHOLD:
                return tuned_threshold(candidate, self.score_step, random)
            case StrategyMutation.DROP_RULE:
                changed = dropped_rule(strategy, random)
            case StrategyMutation.RESTORE_RULE:
                changed = restored_rule(strategy, origin, random)
            case StrategyMutation.EFFECT:
                changed = changed_effect(strategy, random)
            case StrategyMutation.ADD_RULE:
                changed = added_rule(strategy, self.periods, self.levels, random)

        return replace(candidate, strategy=changed) if changed is not None else None


@dataclass(frozen=True)
class BreedingRule:
    """
    The next generation of a search: `count` new candidates, each a parent from the population, the fittest on train
    of `tournament` drawn at random, changed by one to max_mutations mutations of the level drawn at random. A child
    that equals a candidate tried before is drawn again, up to attempts_per_child times per child, so a generation can
    come out short. The same population, tried keys and seed give the same children.
    """

    tournament: PositiveInt
    max_mutations: PositiveInt
    attempts_per_child: PositiveInt
    fitness_rule: SearchFitnessRule
    mutation_rule: StrategyMutationRule

    def apply(
        self, population: Sequence[SearchTrial], tried: Set[str], level: SearchLevel, origin: TechnicalStrategy, count: int, seed: int
    ) -> list[StrategyCandidate]:
        random = Random(seed)
        children: dict[str, StrategyCandidate] = {}

        for _ in range(count * self.attempts_per_child):
            drawn = random.sample(population, min(self.tournament, len(population)))
            child = max(drawn, key=lambda trial: self.fitness_rule.apply(trial.results[SearchSpan.TRAIN])).candidate

            for _ in range(random.randint(1, self.max_mutations)):
                child = self.mutation_rule.apply(child, random.choice(level.mutations), origin, random.getrandbits(64))

            if child.key not in tried:
                children.setdefault(child.key, child)

            if len(children) == count:
                break

        return list(children.values())


@dataclass(frozen=True, kw_only=True)
class StrategySearch:
    """
    One strategy search: what it started from and how, its spans, and what it found. The winners were bred on train
    and picked on validation, so their holdout results are the only ones no choice of the search read. The luck
    baseline is the holdout return of a random sample of the candidates tried that traded enough on train
    (LuckSampleRule): a winner that does not beat most of them was picked by noise.
    """

    inputs: SearchInputs
    started_at: datetime
    finished_at: datetime
    finalists: PositiveInt
    """How many of the best on train were backtested on validation, where the winners were picked among them."""

    breeding: BreedingRule
    """The mutations' bounds, the selection and the fitness the search ran with."""

    split: SessionSplitRule
    spans: dict[SearchSpan, tuple[date, date]]
    tried: PositiveInt
    """The distinct candidates backtested on train."""

    origin: SearchTrial
    """The candidate the search started from, on every span."""

    winners: list[SearchTrial]
    """The best on validation first, each on every span."""

    luck_returns: list[float]
    """The holdout return of each candidate of the luck sample."""

    benchmark: list[Ohlcv]
    """The TAIEX's daily bars from the first session of train to the last of the holdout, oldest first."""

    @property
    def luck_percentiles(self) -> list[float | None]:
        """Each winner's share of the luck sample with a lower holdout return, a tie counting half; None without a sample."""
        returns = self.luck_returns
        holdout = [winner.results[SearchSpan.HOLDOUT].return_pct for winner in self.winners]

        if not returns:
            return [None for _ in holdout]

        return [sum((other < own) + (other == own) / 2 for other in returns) / len(returns) for own in holdout]

    @property
    def benchmark_returns(self) -> dict[SearchSpan, float | None]:
        """The TAIEX's close at each span's last session over its close at the first; None without both."""
        returns: dict[SearchSpan, float | None] = {}

        for span, (first, last) in self.spans.items():
            closes = [bar.close for bar in self.benchmark if first <= bar.ts.date() <= last]
            returns[span] = closes[-1] / closes[0] - 1 if len(closes) > 1 else None

        return returns


@cache
def candidate_json() -> TypeAdapter[StrategyCandidate]:
    return TypeAdapter(StrategyCandidate)


@cache
def indicator_parameters() -> TypeAdapter[IndicatorParameters]:
    return TypeAdapter(IndicatorParameters)


def read_indicators(strategy: TechnicalStrategy) -> dict[FormulaId, IndicatorParameters]:
    """The strategy's indicators its rules read, in id order."""
    read = {
        reference.indicator_id
        for rule in strategy.rules
        for reference, _ in references(rule.condition)
        if isinstance(reference, IndicatorValue)
    }

    return {indicator_id: strategy.indicators[indicator_id] for indicator_id in sorted(read)}


def tuned_period(strategy: TechnicalStrategy, step: float, random: Random) -> TechnicalStrategy | None:
    """One parameter of one indicator the rules read, moved by up to `step` of itself: a period by one bar at least."""
    read = read_indicators(strategy)

    if not read:
        return None

    indicator_id = random.choice(list(read))
    parameters = strategy.indicators[indicator_id]
    name = random.choice([field.name for field in fields(parameters) if field.name != "kind"])
    value = getattr(parameters, name)
    moved = value * (1 + random.uniform(-step, step))

    if isinstance(value, float):
        changed = round(moved, 2)
    else:
        changed = round(moved) if round(moved) != value else value + random.choice((-1, 1))

    return replace(strategy, indicators={**strategy.indicators, indicator_id: replace(parameters, **{name: changed})})


def tuned_constant(strategy: TechnicalStrategy, step: float, random: Random) -> TechnicalStrategy | None:
    """One constant of one condition other than 0, moved by up to `step` of itself, to four significant digits."""
    spots = [
        (index, position, value)
        for index, rule in enumerate(strategy.rules)
        for position, value in enumerate(constants(rule.condition))
        if value != 0
    ]

    if not spots:
        return None

    index, position, value = random.choice(spots)
    rule = strategy.rules[index]
    condition, _ = with_constant(rule.condition, position, float(f"{value * (1 + random.uniform(-step, step)):.4g}"))

    return replace(strategy, rules=replaced(strategy.rules, index, replace(rule, condition=condition)))


def tuned_scoring(strategy: TechnicalStrategy, step: int, random: Random) -> TechnicalStrategy:
    scoring = strategy.scoring
    name = random.choice([field.name for field in fields(scoring)])
    changed = getattr(scoring, name) + random.choice((-1, 1)) * random.randint(1, step)

    return replace(strategy, scoring=replace(scoring, **{name: changed}))


def tuned_threshold(candidate: StrategyCandidate, step: int, random: Random) -> StrategyCandidate:
    name = random.choice(("buy_score", "sell_score"))

    return replace(candidate, **{name: getattr(candidate, name) + random.choice((-1, 1)) * random.randint(1, step)})


def dropped_rule(strategy: TechnicalStrategy, random: Random) -> TechnicalStrategy | None:
    if len(strategy.rules) < 2:
        return None

    index = random.randrange(len(strategy.rules))

    return replace(strategy, rules=strategy.rules[:index] + strategy.rules[index + 1 :])


def restored_rule(strategy: TechnicalStrategy, origin: TechnicalStrategy, random: Random) -> TechnicalStrategy | None:
    """
    A rule of `origin` whose name the strategy lacks, with origin's indicators for those it reads that the strategy
    does not define. One it defines keeps its parameters, which its other rules read too.
    """
    names = {rule.name for rule in strategy.rules}
    missing = [rule for rule in origin.rules if rule.name not in names]

    if not missing:
        return None

    rule = random.choice(missing)
    indicators = {**read_indicators(replace(origin, rules=(rule,))), **strategy.indicators}

    return replace(strategy, indicators=indicators, rules=(*strategy.rules, rule))


def changed_effect(strategy: TechnicalStrategy, random: Random) -> TechnicalStrategy:
    index = random.randrange(len(strategy.rules))
    rule = strategy.rules[index]
    effect = random.choice([effect for effect in RuleEffect if effect is not rule.effect])

    return replace(strategy, rules=replaced(strategy.rules, index, replace(rule, effect=effect)))


def added_rule(
    strategy: TechnicalStrategy, periods: Sequence[int], levels: Mapping[FormulaScale, Sequence[float]], random: Random
) -> TechnicalStrategy | None:
    """
    A rule with a generated condition (generated_condition) and an effect drawn at random, named after its condition.
    It is one of the strategy's rules with the generated name, effect and condition in place of its own, as every
    strategy and rule comes from settings and never from a constructor in code.
    """
    generated = generated_condition(strategy.indicators, periods, levels, random)

    if generated is None:
        return None

    condition, indicators = generated
    effect = random.choice(list(RuleEffect))
    rule = replace(random.choice(strategy.rules), name=rule_label(condition, indicators), effect=effect, condition=condition)

    return replace(strategy, indicators=indicators, rules=(*strategy.rules, rule))


def generated_condition(
    indicators: Mapping[FormulaId, IndicatorParameters],
    periods: Sequence[int],
    levels: Mapping[FormulaScale, Sequence[float]],
    random: Random,
) -> tuple[Comparison, dict[FormulaId, IndicatorParameters]] | None:
    """
    Two numbers of one scale drawn at random, compared by an operator a generated condition uses: a price or a volume
    with another one times a level of its scale, any other number with a level of its scale or with another number of
    its scale. A number is a field of the daily bar, an output of an indicator the strategy defines or of a new
    indicator of one period, `gen_<n>`. None when the scale has too few numbers.
    """
    scale = random.choice(list(FormulaScale))
    left = operand(indicators, scale, periods, random, None)

    if left is None:
        return None

    right = right_side(left[1], scale, left[0], periods, tuple(levels.get(scale, ())), random)

    if right is None:
        return None

    operator = random.choice([operator for operator in ComparisonOperator if operator.generated])

    return Comparison(operator=operator, left=left[0], right=right[0]), right[1]


def right_side(
    indicators: dict[FormulaId, IndicatorParameters],
    scale: FormulaScale,
    left: NumericExpression,
    periods: Sequence[int],
    levels: tuple[float, ...],
    random: Random,
) -> tuple[NumericExpression, dict[FormulaId, IndicatorParameters]] | None:
    if scale.multiplied:
        other = operand(indicators, scale, periods, random, left)
        level = random.choice(levels or (1.0,))

        if other is None or level == 1:
            return other

        return Arithmetic(operator=ArithmeticOperator.MULTIPLY, left=other[0], right=level), other[1]

    if levels and random.choice((True, False)):
        return random.choice(levels), indicators

    return operand(indicators, scale, periods, random, left)


def operand(
    indicators: Mapping[FormulaId, IndicatorParameters],
    scale: FormulaScale,
    periods: Sequence[int],
    random: Random,
    excluded: NumericExpression | None,
) -> tuple[NumericExpression, dict[FormulaId, IndicatorParameters]] | None:
    """A number of the scale other than `excluded`: each held one, and a new indicator of each kind that gives one, as likely."""
    market = [MarketValue(field=field) for field in MarketField if field.scale is scale]
    outputs = [IndicatorValue(indicator_id=indicator_id, output=output) for indicator_id, output in outputs_of(indicators, scale)]
    held: list[NumericExpression] = [expression for expression in [*market, *outputs] if expression != excluded]
    kinds = [kind for kind in IndicatorKind if kind.single_period and any(kind.scale(output) is scale for output in kind.outputs)]

    if not held and not kinds:
        return None

    drawn = random.randrange(len(held) + len(kinds))

    if drawn < len(held):
        return held[drawn], dict(indicators)

    kind = kinds[drawn - len(held)]
    indicator_id = next(f"gen_{number}" for number in range(1, len(indicators) + 2) if f"gen_{number}" not in indicators)
    parameters = indicator_parameters().validate_python({"kind": kind, "period": random.choice(periods)})
    output = random.choice([output for output in kind.outputs if kind.scale(output) is scale])

    return IndicatorValue(indicator_id=indicator_id, output=output), {**indicators, indicator_id: parameters}


def outputs_of(indicators: Mapping[FormulaId, IndicatorParameters], scale: FormulaScale) -> list[tuple[FormulaId, IndicatorOutput]]:
    return [
        (indicator_id, output)
        for indicator_id, parameters in sorted(indicators.items())
        for output in parameters.kind.outputs
        if parameters.kind.scale(output) is scale
    ]


def rule_label(condition: Comparison, indicators: Mapping[FormulaId, IndicatorParameters]) -> str:
    """The condition in words, such as `close crosses_above sma(20) multiply 1.05`."""
    return f"{expression_label(condition.left, indicators)} {condition.operator} {expression_label(condition.right, indicators)}"


def expression_label(expression: NumericExpression, indicators: Mapping[FormulaId, IndicatorParameters]) -> str:
    match expression:
        case MarketValue(field=field):
            return str(field)
        case IndicatorValue(indicator_id=indicator_id, output=output):
            parameters = indicators[indicator_id]
            values = ", ".join(str(getattr(parameters, field.name)) for field in fields(parameters) if field.name != "kind")
            return f"{parameters.kind}({values})" + ("" if output is IndicatorOutput.VALUE else f" {output}")
        case Arithmetic(operator=operator, left=left, right=right):
            return f"{expression_label(left, indicators)} {operator} {expression_label(right, indicators)}"
        case _:
            return f"{expression:g}" if isinstance(expression, float | int) else str(expression)


def constants(node: Condition | NumericExpression) -> Iterator[float]:
    """Every constant number of the formula, left before right."""
    match node:
        case ConditionGroup(conditions=conditions):
            for part in conditions:
                yield from constants(part)
        case Comparison(left=left, right=right) | Arithmetic(left=left, right=right):
            yield from constants(left)
            yield from constants(right)
        case float() | int():
            yield float(node)
        case _:
            return


def with_constant(node: Condition | NumericExpression, position: int, value: float) -> tuple[Any, int]:
    """The formula with its constant at `position`, counted as constants() counts, set to `value`; and how many it holds."""
    match node:
        case ConditionGroup(conditions=conditions):
            parts, seen = [], 0

            for part in conditions:
                changed, held = with_constant(part, position - seen, value)
                parts.append(changed)
                seen += held

            return replace(node, conditions=tuple(parts)), seen
        case Comparison(left=left, right=right) | Arithmetic(left=left, right=right):
            changed_left, held_left = with_constant(left, position, value)
            changed_right, held_right = with_constant(right, position - held_left, value)
            return replace(node, left=changed_left, right=changed_right), held_left + held_right
        case float() | int():
            return (value if position == 0 else node), 1
        case _:
            return node, 0


def replaced(rules: tuple[TechnicalRule, ...], index: int, rule: TechnicalRule) -> tuple[TechnicalRule, ...]:
    return (*rules[:index], rule, *rules[index + 1 :])
