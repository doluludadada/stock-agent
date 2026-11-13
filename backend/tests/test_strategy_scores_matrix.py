"""
StrategyScoresRule scores every stock at every session of a DailyBarMatrix at once. Each cell must be exactly what
TechnicalStrategy.apply reports on the stock's bars of that session's window, with the session's close as the latest
price: the same score and the same pass. A missing bar, a window too short for the strategy and a formula that reads an
unavailable input each score 0 and fail, as they do live.
"""

import random
from collections import Counter
from collections.abc import Iterator
from datetime import UTC, date, datetime, time, timedelta
from functools import cache
from math import sqrt
from typing import Any

import numpy as np
import pytest
from pydantic import TypeAdapter, ValidationError
from support.formulas import LATEST_PRICE, Json, arithmetic, compare, group, indicator, market, rule
from support.settings import shipped_config

from a_domain.model.market.ohlcv import Ohlcv
from a_domain.model.market.stock import Stock
from a_domain.rules.technical.calculation.calculator import IndicatorParameters, indicator_outputs
from a_domain.rules.technical.matrix import DailyBarMatrix, StrategyScoresRule
from a_domain.rules.technical.strategy import TechnicalStrategy
from a_domain.types.enums import ArithmeticOperator, ComparisonOperator, IndicatorKind, MarketField, RuleEffect

STRATEGY = TypeAdapter(TechnicalStrategy)
INDICATOR: TypeAdapter[IndicatorParameters] = TypeAdapter(IndicatorParameters)
BALANCED = next(strategy for strategy in shipped_config().technical.built_in_strategies if strategy.strategy_id == "balanced")


def random_matrix(stocks: int, sessions: int, seed: int) -> DailyBarMatrix:
    """
    Random walks priced in cents, with what trips a scalar formula: missing sessions, stocks listed late, prices flat
    for weeks, closes repeated exactly, sessions without volume, and a few infinite prices. Two stocks miss no session:
    one priced in quarters whose high and low spread evenly around its close, so a rise of the high ties a fall of the
    low; and one whose closes alternate between the two of squaring_apart.
    """
    generator = np.random.default_rng(seed)
    shape = (stocks, sessions)
    returns = generator.normal(
        generator.uniform(-0.004, 0.006, (stocks, 1)), generator.choice([0.008, 0.02, 0.04], (stocks, 1)), shape
    )
    close = np.round(np.maximum(0.5, generator.uniform(8, 300, (stocks, 1)) * np.cumprod(1 + returns, axis=1)), 2)
    repeated = generator.random(shape) < 0.1

    for session in range(1, sessions):
        close[:, session] = np.where(repeated[:, session], close[:, session - 1], close[:, session])

    spread = close * generator.uniform(0.002, 0.08, shape)
    low = np.round(close - spread * generator.random(shape), 2)
    high = np.round(low + spread, 2)
    opening = np.round(generator.uniform(low, high), 2)
    volume = np.where(generator.random(shape) < 0.05, 0.0, np.round(10 ** generator.uniform(2, 7, shape)))

    for stock in range(0, stocks, 3):
        start = int(generator.integers(0, sessions - 30))
        flat = slice(start, start + 30)
        opening[stock, flat] = high[stock, flat] = low[stock, flat] = close[stock, flat] = close[stock, start]
        volume[stock, flat] = volume[stock, start]

    close[1] = opening[1] = np.round(close[1] * 4) / 4
    half_range = generator.integers(1, 5, sessions) / 4
    high[1], low[1] = close[1] + half_range, close[1] - half_range
    close[2] = opening[2] = np.where(np.arange(sessions) % 2, *squaring_apart())
    high[2], low[2] = close[2] + 0.5, close[2] - 0.5

    for field in (high, low, close):
        field[generator.random(shape) < 0.003] = np.inf if field is not low else -np.inf

    missing = (generator.random(shape) < 0.05) | (
        np.arange(sessions) < generator.integers(0, sessions // 2, (stocks, 1)) * (generator.random((stocks, 1)) < 0.3)
    )
    missing[1:3] = False
    fields = {
        name: np.where(missing, np.nan, values)
        for name, values in (("open", opening), ("high", high), ("low", low), ("close", close), ("volume", volume))
    }
    first = date(2026, 1, 5)
    return DailyBarMatrix(
        stock_ids=tuple(f"S{stock}" for stock in range(stocks)),
        sessions=tuple(first + timedelta(days=day) for day in range(sessions)),
        **fields,
    )


@cache
def squaring_apart() -> tuple[float, float]:
    """
    Two closes that, alternating, give a Bollinger deviation over 2 and over 20 bars that comes out apart when the squares
    are x ** 2, which CPython computes through the C library's pow, and when they are x * x. Where pow squares exactly,
    no pair does and any pair serves.
    """
    generator = random.Random(0)

    for _ in range(100_000):
        pair = (round(generator.uniform(10, 300), 2), round(generator.uniform(10, 300), 2))

        if all(deviation(window, power=True) != deviation(window, power=False) for window in (pair, pair * 10, pair[::-1] * 10)):
            return pair

    return 10.0, 11.0


def deviation(window: tuple[float, ...], *, power: bool) -> float:
    middle = sum(window) / len(window)
    return sqrt(sum((value - middle) ** 2 if power else (value - middle) * (value - middle) for value in window) / len(window))


def window_starts(sessions: int, longest: int, seed: int) -> list[int]:
    """Each session's window reaches back up to `longest` sessions, sometimes to itself alone, sometimes to the first session."""
    generator = random.Random(seed)
    return [max(0, session - generator.randint(0, longest)) for session in range(sessions)]


def live_windows(matrix: DailyBarMatrix, starts: list[int]) -> dict[tuple[int, int], list[Ohlcv]]:
    """The bars of each session's window, by (stock, session), for each session the stock has a bar of."""
    bars = [[bar(matrix, stock, session) for session in range(len(matrix.sessions))] for stock in range(len(matrix.stock_ids))]
    return {
        (stock, session): [bar for bar in stock_bars[starts[session] : session + 1] if bar is not None]
        for stock, stock_bars in enumerate(bars)
        for session, latest in enumerate(stock_bars)
        if latest is not None
    }


def live_scores(strategy: TechnicalStrategy, matrix: DailyBarMatrix, starts: list[int]) -> tuple[np.ndarray, np.ndarray, Counter[str]]:
    """TechnicalStrategy.apply on each stock's bars of each session's window, and how many cells ended each way."""
    score, passed = np.zeros(matrix.close.shape, dtype=np.int64), np.zeros(matrix.close.shape, dtype=np.bool_)
    outcomes = Counter({"no bar": int(np.isnan(matrix.close).sum())})

    for (stock, session), window in live_windows(matrix, starts).items():
        report = strategy.apply(Stock(stock_id=matrix.stock_ids[stock], ohlcv=window))
        score[stock, session], passed[stock, session] = report.score, report.passed
        outcomes[outcome(report.hard_failures, report.passed)] += 1

    return score, passed, outcomes


def bar(matrix: DailyBarMatrix, stock: int, session: int) -> Ohlcv | None:
    if np.isnan(matrix.close[stock, session]):
        return None

    return Ohlcv(
        ts=datetime.combine(matrix.sessions[session], time(5, 30), UTC),
        open=float(matrix.open[stock, session]),
        high=float(matrix.high[stock, session]),
        low=float(matrix.low[stock, session]),
        close=float(matrix.close[stock, session]),
        volume=int(matrix.volume[stock, session]),
    )


def outcome(hard_failures: list[str], passed: bool) -> str:
    if passed:
        return "passed"

    if hard_failures[0].startswith("Need "):
        return "window too short"

    return "data unavailable" if hard_failures[0].startswith("Technical data unavailable") else "failed"


def assert_every_cell_matches(strategy: TechnicalStrategy, matrix: DailyBarMatrix, starts: list[int]) -> Counter[str]:
    expected_score, expected_passed, outcomes = live_scores(strategy, matrix, starts)
    scores = StrategyScoresRule(strategy).apply(matrix, starts)
    wrong = np.argwhere((scores.score != expected_score) | (scores.passed != expected_passed))
    cells = [
        (int(stock), int(session), int(expected_score[stock, session]), int(scores.score[stock, session]))
        for stock, session in wrong[:5]
    ]
    assert not len(wrong), f"{strategy.strategy_id}: {len(wrong)} cells differ; (stock, session, live, matrix): {cells}"
    return outcomes


def test_the_built_in_strategy_scores_every_cell_as_the_live_strategy() -> None:
    [strategy] = shipped_config().technical.built_in_strategies

    outcomes = assert_every_cell_matches(strategy, random_matrix(40, 150, 7), window_starts(150, 130, 8))

    assert min(outcomes[name] for name in ("passed", "failed", "data unavailable", "window too short", "no bar")) > 0, outcomes


def test_random_strategies_score_every_cell_as_the_live_strategy() -> None:
    generator = random.Random(23)
    matrix, starts = random_matrix(12, 60, 3), window_starts(60, 50, 4)
    reached: set[str] = set()
    outcomes: Counter[str] = Counter()

    for index in range(60):
        outcomes += assert_every_cell_matches(random_strategy(generator, index, reached), matrix, starts)

    every_part = {f"{kind}.{output}" for kind in IndicatorKind for output in kind.outputs}
    every_part |= {*ComparisonOperator, *ArithmeticOperator, *MarketField, *RuleEffect, "latest_price", "bars_ago", "nested group"}
    assert every_part <= reached, every_part - reached
    assert min(outcomes[name] for name in ("passed", "failed", "data unavailable", "window too short")) > 0, outcomes


@pytest.mark.parametrize("kind", list(IndicatorKind))
def test_a_rule_at_an_indicators_exact_live_value_holds_where_it_does_live(kind: IndicatorKind) -> None:
    """
    Each rule compares an indicator output with its exact live value at one random window, so it holds there only if the
    matrix computed that output to the last bit. A strategy of 100 such rules scores how many of them hold.
    """
    generator = random.Random(kind)
    matrix, starts = random_matrix(12, 90, 5), window_starts(90, 85, 6)
    windows = live_windows(matrix, starts)
    built_in = next(parameters for parameters in BALANCED.indicators.values() if parameters.kind == kind)

    for parameters in (INDICATOR.validate_python(random_indicator(generator, kind)), built_in):
        rules = [
            rule(f"pin {number}", pin, "increase_score_on_pass") for number, pin in enumerate(pins(generator, parameters, windows))
        ]
        document = {
            "indicators": {"ind_a": INDICATOR.dump_python(parameters)},
            "rules": rules,
            "scoring": {"base_score": 0, "pass_score_increase": 1},
        }
        strategy = STRATEGY.validate_python({"strategy_id": "pinned", "name": "Pinned", **document})

        assert_every_cell_matches(strategy, matrix, starts)


def pins(generator: random.Random, parameters: IndicatorParameters, windows: dict[tuple[int, int], list[Ohlcv]]) -> Iterator[Json]:
    """100 comparisons of an output, some bars ago, with its exact live value at a random window long enough to give it."""
    cells = [window for window in windows.values() if len(window) >= parameters.required_bars + 2]
    found = 0

    while found < 100:
        window, output, bars_ago = generator.choice(cells), generator.choice(parameters.kind.outputs), generator.choice([0, 0, 1, 2])
        value = indicator_outputs(parameters, window[: len(window) - bars_ago]).get(output)

        if value is not None:
            found += 1
            yield compare(indicator("ind_a", output, bars_ago), "eq", value)


def test_a_window_that_starts_after_its_session_is_refused() -> None:
    strategy = shipped_config().technical.built_in_strategies[0]

    with pytest.raises(ValueError, match="window_starts"):
        StrategyScoresRule(strategy).apply(random_matrix(3, 40, 1), [*range(39), 40])


def test_a_bar_without_every_field_is_refused() -> None:
    fields = {name: np.ones((1, 2)) for name in ("open", "high", "low", "close", "volume")}
    fields["volume"][0, 1] = np.nan

    with pytest.raises(ValidationError, match="every field"):
        DailyBarMatrix(stock_ids=("2330",), sessions=(date(2026, 1, 5), date(2026, 1, 6)), **fields)


def random_strategy(generator: random.Random, index: int, reached: set[str]) -> TechnicalStrategy:
    """A strategy of up to four indicators with short periods and up to five rules over them."""
    indicators = {
        f"ind_{position}": random_indicator(generator, kind) for position, kind in enumerate(generator.sample(list(IndicatorKind), 4))
    }
    rules = []

    for number in range(generator.randint(1, 5)):
        effect = generator.choice(list(RuleEffect))
        reached.add(effect)
        rules.append(rule(f"rule {number}", random_condition(generator, indicators, 2, reached), effect))

    scoring = {
        "base_score": generator.randint(0, 100),
        **{name: generator.randint(0, 30) for name in ("block_failure_penalty", "failure_score_reduction", "pass_score_increase")},
    }
    return STRATEGY.validate_python(
        {"strategy_id": f"random_{index}", "name": f"Random {index}", "indicators": indicators, "scoring": scoring, "rules": rules}
    )


def random_indicator(generator: random.Random, kind: IndicatorKind) -> Json:
    match kind:
        case IndicatorKind.MACD:
            fast = generator.randint(1, 5)
            return {"kind": kind, "fast": fast, "slow": fast + generator.randint(1, 6), "signal": generator.randint(1, 5)}
        case IndicatorKind.BOLLINGER:
            return {"kind": kind, "period": generator.randint(1, 12), "std": generator.choice([0.5, 1.0, 2.0, 2.5])}
        case IndicatorKind.STOCHASTIC:
            return {"kind": kind, "k_period": generator.randint(1, 9), "d_period": generator.randint(1, 4)}
        case IndicatorKind.ADX:
            return {"kind": kind, "period": generator.randint(1, 7)}
        case _:
            return {"kind": kind, "period": generator.randint(1, 12)}


def random_condition(generator: random.Random, indicators: dict[str, Json], depth: int, reached: set[str]) -> Json:
    if depth and generator.random() < 0.3:
        if depth == 1:
            reached.add("nested group")

        parts = [random_condition(generator, indicators, depth - 1, reached) for _ in range(generator.randint(1, 3))]
        return group(generator.choice(["all", "any"]), *parts)

    operator = generator.choice(list(ComparisonOperator))
    reached.add(operator)
    left, right = (random_expression(generator, indicators, 1, not operator.is_crossing, reached) for _ in range(2))
    return compare(left if reads_data(left) or reads_data(right) else market("close"), operator, right)


def random_expression(generator: random.Random, indicators: dict[str, Json], depth: int, latest_price: bool, reached: set[str]) -> Any:
    roll, bars_ago = generator.random(), generator.choice([0, 0, 0, 1, 2, 3])

    if depth and roll < 0.25:
        operator = generator.choice(list(ArithmeticOperator))
        reached.add(operator)
        left, right = (random_expression(generator, indicators, depth - 1, latest_price, reached) for _ in range(2))
        return arithmetic(left, operator, right)

    if roll < 0.4:
        return generator.choice([0.0, 0.5, 1.0, 2.0, 50.0, 100.0, round(generator.uniform(-5, 300), 2)])

    if roll < 0.62 and latest_price:
        reached.add("latest_price")
        return LATEST_PRICE

    reached.update({"bars_ago"} if bars_ago else set())

    if roll < 0.7:
        field = generator.choice(list(MarketField))
        reached.add(field)
        return market(field, bars_ago)

    indicator_id = generator.choice(list(indicators))
    output = generator.choice(IndicatorKind(indicators[indicator_id]["kind"]).outputs)
    reached.add(f"{indicators[indicator_id]['kind']}.{output}")
    return indicator(indicator_id, output, bars_ago)


def reads_data(expression: Any) -> bool:
    if not isinstance(expression, dict):
        return False

    if expression["type"] == "arithmetic":
        return reads_data(expression["left"]) or reads_data(expression["right"])

    return True
