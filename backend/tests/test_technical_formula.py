"""
How a strategy's formulas score a stock. Each strategy is built from JSON, the form the Web API receives, and each
history is chosen so that the expected verdict follows from the requirement by hand.
"""

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import TypeAdapter
from support.formulas import LATEST_PRICE, Json, arithmetic, compare, group, indicator, market, rule

from a_domain.model.analysis.technical_report import TechnicalReport
from a_domain.model.market.ohlcv import Ohlcv
from a_domain.model.market.stock import Stock
from a_domain.rules.technical.strategy import TechnicalStrategy

FIRST_SESSION = datetime(2026, 1, 5, 13, 30, tzinfo=UTC)
CLOSE, VOLUME = market("close"), market("volume")


def daily_bars(closes: list[float], volumes: list[int] | None = None) -> list[Ohlcv]:
    """One completed bar per trading day, oldest first, opening, peaking and bottoming at its close."""
    return [
        Ohlcv(ts=FIRST_SESSION + timedelta(days=day), open=close, high=close, low=close, close=close, volume=volume)
        for day, (close, volume) in enumerate(zip(closes, volumes or [1000] * len(closes), strict=True))
    ]


def stock(bars: list[Ohlcv], realtime_price: float | None = None) -> Stock:
    stock = Stock(stock_id="2330")
    stock.load_history(bars)

    if realtime_price is not None:
        stock.realtime_bar = Ohlcv(ts=bars[-1].ts + timedelta(hours=20), close=realtime_price, volume=1000)

    return stock


def strategy(*rules: Json, indicators: Json | None = None, scoring: Json | None = None) -> TechnicalStrategy:
    document = {"strategy_id": "probe", "name": "Probe", "indicators": indicators or {}, "scoring": scoring or {}, "rules": rules}
    return TypeAdapter(TechnicalStrategy).validate_python(document)


def holds(condition: Json, bars: list[Ohlcv], indicators: Json | None = None, realtime_price: float | None = None) -> bool:
    """Whether the condition holds at the latest bar. A condition the strategy cannot evaluate fails the test."""
    report = strategy(rule("Probe", condition), indicators=indicators).apply(stock(bars, realtime_price))

    assert report.hard_failures in ([], ["Probe"]), report.hard_failures
    return report.passed


# --------------------------- Parameters are data --------------------------- #

TREND_AND_VOLUME = strategy(
    rule(
        "My trend and volume",
        group(
            "all",
            compare(indicator("ind_a"), "crosses_above", indicator("ind_b")),
            compare(VOLUME, "gt", arithmetic(indicator("ind_c", bars_ago=1), "multiply", 1.8)),
        ),
    ),
    rule("Close above the long average", compare(CLOSE, "gt", indicator("ind_b")), "reduce_score_on_fail"),
    indicators={
        "ind_a": {"kind": "sma", "period": 37},
        "ind_b": {"kind": "sma", "period": 83},
        "ind_c": {"kind": "volume_sma", "period": 25},
    },
)

CROSSING_DAY = daily_bars([1000.0] * 19 + [100.0] * 82 + [200.0], volumes=[1000] * 101 + [1801])
"""
On the last of these 102 bars the 37-day average, 3800/37 = 102.7, is above the 83-day one, 8400/83 = 101.2, and a bar
earlier it was below it: 100 against 9200/83 = 110.8. The 101-day average, 26400/101 = 261.4, stays above both. The last
volume, 1801 shares, is just over 1.8 times the 1000-share average of the 25 bars before it.
"""


def with_long_period(period: int) -> TechnicalStrategy:
    long_average = replace(TREND_AND_VOLUME.indicators["ind_b"], period=period)
    return replace(TREND_AND_VOLUME, indicators=TREND_AND_VOLUME.indicators | {"ind_b": long_average})


def test_a_crossing_of_two_chosen_averages_with_a_volume_multiple_holds_on_the_crossing_bar() -> None:
    assert TREND_AND_VOLUME.required_bars == 84
    assert TREND_AND_VOLUME.apply(stock(CROSSING_DAY)) == TechnicalReport(score=50)
    assert TREND_AND_VOLUME.apply(stock(CROSSING_DAY[-84:])) == TechnicalReport(score=50)


def test_a_new_period_under_the_same_indicator_id_changes_every_rule_that_reads_it() -> None:
    longer = with_long_period(101)

    assert longer.required_bars == 102
    assert longer.apply(stock(CROSSING_DAY)) == TechnicalReport(
        score=30, hard_failures=["My trend and volume"], soft_failures=["Close above the long average"]
    )


def test_renaming_the_rules_and_the_strategy_changes_no_result() -> None:
    renamed = replace(
        TREND_AND_VOLUME,
        name="Renamed",
        rules=tuple(replace(rule, name=f"Rule {position}") for position, rule in enumerate(TREND_AND_VOLUME.rules)),
    )

    assert renamed.required_bars == 84
    assert renamed.apply(stock(CROSSING_DAY)) == TechnicalReport(score=50)
    assert renamed.apply(stock(CROSSING_DAY[:-1])) == TechnicalReport(score=30, hard_failures=["Rule 0"], soft_failures=["Rule 1"])
    assert TREND_AND_VOLUME.apply(stock(CROSSING_DAY[:-1])) == TechnicalReport(
        score=30, hard_failures=["My trend and volume"], soft_failures=["Close above the long average"]
    )


# ------------------------- Several indicators of a kind ------------------------- #


def test_several_moving_averages_coexist_under_their_own_ids() -> None:
    indicators = {
        "ind_a": {"kind": "sma", "period": 5},
        "ind_b": {"kind": "sma", "period": 10},
        "ind_c": {"kind": "sma", "period": 20},
    }
    one_to_twenty = daily_bars([float(close) for close in range(1, 21)])

    assert holds(
        group(
            "all",
            compare(indicator("ind_a"), "eq", 18),
            compare(indicator("ind_b"), "eq", 15.5),
            compare(indicator("ind_c"), "eq", 10.5),
        ),
        one_to_twenty,
        indicators,
    )


FLAT_THEN_JUMP = daily_bars([100.0] * 39 + [120.0])
"""
After a flat stretch every average is 100, so on the jump an n-bar EMA is 100 + 20 x 2/(n+1). The MACD 12/26 line is
20 x (2/13 - 2/27) = 1.5954, its 9-bar signal is 1.5954 x 2/10 = 0.3191 and its histogram 1.2763. The MACD 3/6 line is
20 x (2/4 - 2/7) = 4.2857.
"""


def between(value: Json, low: float, high: float) -> Json:
    return group("all", compare(value, "gt", low), compare(value, "lt", high))


def test_the_macd_line_signal_and_histogram_are_outputs_of_one_indicator() -> None:
    indicators = {"ind_m": {"kind": "macd", "fast": 12, "slow": 26, "signal": 9}}
    line, signal, histogram = (indicator("ind_m", output) for output in ("line", "signal", "histogram"))

    assert holds(
        group(
            "all",
            compare(line, "gt", signal),
            between(line, 1.595, 1.596),
            between(signal, 0.319, 0.3192),
            between(histogram, 1.276, 1.277),
        ),
        FLAT_THEN_JUMP,
        indicators,
    )


def test_two_macd_indicators_with_different_parameters_stay_separate() -> None:
    indicators = {
        "ind_m": {"kind": "macd", "fast": 12, "slow": 26, "signal": 9},
        "ind_n": {"kind": "macd", "fast": 3, "slow": 6, "signal": 2},
    }
    slow_line, fast_line = indicator("ind_m", "line"), indicator("ind_n", "line")

    assert holds(group("all", between(slow_line, 1.595, 1.596), between(fast_line, 4.285, 4.286)), FLAT_THEN_JUMP, indicators)
    assert holds(compare(fast_line, "gt", slow_line), FLAT_THEN_JUMP, indicators)
    assert not holds(compare(slow_line, "gt", fast_line), FLAT_THEN_JUMP, indicators)


# ----------------------- Arithmetic, comparison, crossing ----------------------- #

TWELVE_AFTER_EIGHT = daily_bars([8.0, 12.0])


@pytest.mark.parametrize(
    ("formula", "value"),
    [
        (arithmetic(CLOSE, "add", 3), 15),
        (arithmetic(CLOSE, "subtract", 3), 9),
        (arithmetic(CLOSE, "multiply", 2), 24),
        (arithmetic(CLOSE, "divide", 3), 4),
        (arithmetic(arithmetic(arithmetic(CLOSE, "add", 4), "multiply", 2), "divide", 8), 4),
        (arithmetic(100, "subtract", arithmetic(CLOSE, "divide", market("close", 1))), 98.5),
    ],
    ids=["add", "subtract", "multiply", "divide", "nested", "constant-on-the-left"],
)
def test_arithmetic_combines_market_values_and_constants(formula: Json, value: float) -> None:
    assert holds(compare(formula, "eq", value), TWELVE_AFTER_EIGHT)


@pytest.mark.parametrize(
    ("operator", "against_11_12_13"),
    [
        ("gt", (True, False, False)),
        ("gte", (True, True, False)),
        ("lt", (False, False, True)),
        ("lte", (False, True, True)),
        ("eq", (False, True, False)),
        ("ne", (True, False, True)),
    ],
)
def test_each_comparison_at_and_around_its_boundary(operator: str, against_11_12_13: tuple[bool, bool, bool]) -> None:
    assert tuple(holds(compare(CLOSE, operator, bound), TWELVE_AFTER_EIGHT) for bound in (11, 12, 13)) == against_11_12_13


@pytest.mark.parametrize(
    ("operator", "closes", "crosses"),
    [
        ("crosses_above", [9, 11], True),
        ("crosses_above", [10, 11], True),
        ("crosses_above", [11, 12], False),
        ("crosses_above", [9, 11, 12], False),
        ("crosses_above", [9, 10], False),
        ("crosses_above", [11, 9], False),
        ("crosses_below", [11, 9], True),
        ("crosses_below", [10, 9], True),
        ("crosses_below", [9, 8], False),
        ("crosses_below", [11, 9, 8], False),
        ("crosses_below", [11, 10], False),
        ("crosses_below", [9, 11], False),
    ],
    ids=[
        "above-from-below",
        "above-from-equal",
        "above-staying-above",
        "above-a-bar-after-the-cross",
        "above-reaching-equal",
        "above-going-down",
        "below-from-above",
        "below-from-equal",
        "below-staying-below",
        "below-a-bar-after-the-cross",
        "below-reaching-equal",
        "below-going-up",
    ],
)
def test_a_crossing_holds_only_on_the_bar_where_it_happens(operator: str, closes: list[float], crosses: bool) -> None:
    assert holds(compare(CLOSE, operator, 10), daily_bars(closes)) is crosses


def test_a_crossing_reads_each_whole_side_one_bar_earlier() -> None:
    change = arithmetic(CLOSE, "subtract", market("close", 1))
    three_day_average_plus_half = arithmetic(indicator("ind_a"), "add", 0.5)
    three_day_average = {"ind_a": {"kind": "sma", "period": 3}}

    assert holds(compare(change, "crosses_above", 0), daily_bars([10, 8, 9])), "the change went from 8 - 10 = -2 to 9 - 8 = 1"
    assert not holds(compare(change, "crosses_above", 0), daily_bars([8, 10, 11])), "the change stayed positive: 2, then 1"
    assert holds(compare(CLOSE, "crosses_above", three_day_average_plus_half), daily_bars([20, 5, 9, 11]), three_day_average), (
        "the close 9 was under (20 + 5 + 9)/3 + 0.5 = 11.83; now 11 is over (5 + 9 + 11)/3 + 0.5 = 8.83"
    )


def test_bars_ago_counts_completed_trading_days_back_for_market_and_indicator_values() -> None:
    tuesday_to_monday = (6, 7, 8, 9, 12)
    over_a_weekend = [
        Ohlcv(ts=datetime(2026, 1, day, 13, 30, tzinfo=UTC), open=close, high=close, low=close, close=close, volume=volume)
        for day, close, volume in zip(tuesday_to_monday, (10, 20, 30, 40, 50), (100, 200, 300, 400, 500), strict=True)
    ]

    assert holds(
        group(
            "all",
            compare(market("close", 1), "eq", 40),
            compare(market("close", 2), "eq", 30),
            compare(market("volume", 4), "eq", 100),
            compare(indicator("ind_a", bars_ago=1), "eq", 35),
            compare(indicator("ind_a", bars_ago=3), "eq", 15),
        ),
        over_a_weekend,
        {"ind_a": {"kind": "sma", "period": 2}},
    )


def test_the_latest_price_is_the_realtime_quote_when_there_is_one_else_the_latest_close() -> None:
    assert holds(compare(LATEST_PRICE, "gt", 11), daily_bars([10.0]), realtime_price=12.0)
    assert not holds(compare(LATEST_PRICE, "gt", 11), daily_bars([10.0]))


YES, NO = compare(CLOSE, "gt", 11), compare(CLOSE, "gt", 13)


@pytest.mark.parametrize(
    ("condition", "expected"),
    [
        (group("all", YES, YES), True),
        (group("all", YES, NO), False),
        (group("any", NO, YES), True),
        (group("any", NO, NO), False),
        (group("all", group("any", NO, YES), group("all", YES, YES)), True),
        (group("all", group("any", NO, NO), YES), False),
        (group("any", group("all", YES, NO), group("any", NO, group("all", YES, YES))), True),
        (group("any", group("all", YES, NO), group("any", NO, group("all", YES, NO))), False),
    ],
)
def test_all_and_any_groups_nest(condition: Json, expected: bool) -> None:
    assert holds(condition, TWELVE_AFTER_EIGHT) is expected


# ------------------------------- Unavailable data ------------------------------- #


@pytest.mark.parametrize(
    ("condition", "bars", "indicators"),
    [
        pytest.param(
            compare(arithmetic(VOLUME, "divide", indicator("ind_v", bars_ago=1)), "gt", 1.8),
            daily_bars([10.0] * 6, volumes=[0] * 6),
            {"ind_v": {"kind": "volume_sma", "period": 5}},
            id="volume-over-an-average-of-no-trades",
        ),
        pytest.param(
            compare(arithmetic(CLOSE, "divide", arithmetic(CLOSE, "subtract", CLOSE)), "lt", 1),
            TWELVE_AFTER_EIGHT,
            {},
            id="division-by-zero",
        ),
        pytest.param(
            compare(CLOSE, "gt", indicator("ind_a")),
            daily_bars([1e308, 1e308]),
            {"ind_a": {"kind": "sma", "period": 2}},
            id="indicator-output-that-overflows",
        ),
        pytest.param(compare(arithmetic(CLOSE, "multiply", 1e308), "lt", 0), TWELVE_AFTER_EIGHT, {}, id="non-finite-result"),
        pytest.param(
            compare(market("close", 1), "gt", 10),
            [Ohlcv(ts=FIRST_SESSION - timedelta(days=1), close=float("nan"), volume=1000), *daily_bars([12.0])],
            {},
            id="non-finite-daily-close",
        ),
    ],
)
def test_unavailable_data_fails_the_stock_naming_its_rule_and_no_other_rule_counts(
    condition: Json, bars: list[Ohlcv], indicators: Json
) -> None:
    probe = strategy(
        rule("Holds", compare(CLOSE, "gt", 0), "increase_score_on_pass"),
        rule("Reads unavailable data", condition, "reduce_score_on_fail"),
        rule("Fails", compare(CLOSE, "lt", 0), "reduce_score_on_fail"),
        indicators=indicators,
    )

    assert probe.apply(stock(bars)) == TechnicalReport(score=0, hard_failures=["Technical data unavailable: Reads unavailable data"])


UNAVAILABLE = compare(arithmetic(CLOSE, "divide", 0), "gt", 1)


@pytest.mark.parametrize(
    "condition",
    [
        group("any", YES, UNAVAILABLE),
        group("any", UNAVAILABLE, YES),
        group("all", NO, UNAVAILABLE),
        group("all", YES, group("any", YES, UNAVAILABLE)),
    ],
    ids=["any-holding-first", "any-holding-last", "all-failing-first", "nested"],
)
def test_a_group_with_an_unavailable_part_is_unavailable_whatever_its_other_parts_say(condition: Json) -> None:
    report = strategy(rule("Group", condition, "increase_score_on_pass")).apply(stock(TWELVE_AFTER_EIGHT))

    assert report == TechnicalReport(score=0, hard_failures=["Technical data unavailable: Group"])


def test_every_rule_that_reads_unavailable_data_is_named() -> None:
    probe = strategy(rule("First", UNAVAILABLE), rule("Available", YES), rule("Second", group("all", YES, UNAVAILABLE)))

    assert probe.apply(stock(TWELVE_AFTER_EIGHT)) == TechnicalReport(
        score=0, hard_failures=["Technical data unavailable: First, Second"]
    )


def test_fewer_daily_bars_than_required_fail_the_stock_before_any_rule() -> None:
    assert TREND_AND_VOLUME.apply(stock(CROSSING_DAY[-83:])) == TechnicalReport(
        score=0, hard_failures=["Need 84 daily bars; received 83"]
    )
    assert TREND_AND_VOLUME.apply(stock([])) == TechnicalReport(score=0, hard_failures=["Need 84 daily bars; received 0"])


@pytest.mark.parametrize(
    ("condition", "indicators", "required_bars"),
    [
        (compare(CLOSE, "gt", indicator("ind_a")), {"ind_a": {"kind": "sma", "period": 83}}, 83),
        (compare(CLOSE, "crosses_above", indicator("ind_a")), {"ind_a": {"kind": "sma", "period": 83}}, 84),
        (compare(CLOSE, "gt", indicator("ind_a", bars_ago=2)), {"ind_a": {"kind": "sma", "period": 83}}, 85),
        (compare(VOLUME, "gt", indicator("ind_v", bars_ago=1)), {"ind_v": {"kind": "volume_sma", "period": 25}}, 26),
        (compare(market("close", 4), "crosses_below", 10), {}, 6),
        (compare(LATEST_PRICE, "gte", 15), {}, 1),
        (group("any", compare(LATEST_PRICE, "gte", 15), compare(market("open", 9), "gt", 0)), {}, 10),
    ],
    ids=[
        "average",
        "average-crossing",
        "average-2-bars-ago",
        "previous-average-volume",
        "crossing-4-bars-ago",
        "latest-price",
        "deepest-part",
    ],
)
def test_required_bars_is_the_longest_history_any_part_reads(condition: Json, indicators: Json, required_bars: int) -> None:
    assert strategy(rule("Rule", condition), indicators=indicators).required_bars == required_bars


# --------------------------- Previous-N-day volume --------------------------- #

PREVIOUS_25 = [1000, 3000] * 12 + [2000]
"""Volumes, in shares, that average exactly 2000."""

VOLUME_DAY = daily_bars([10.0] * 27, volumes=[9_000_000, *PREVIOUS_25, 5000])
AVERAGE_VOLUME = {"ind_v": {"kind": "volume_sma", "period": 25}}


def test_the_previous_25_day_average_volume_leaves_out_the_latest_bar() -> None:
    assert holds(compare(indicator("ind_v", bars_ago=1), "eq", 2000), VOLUME_DAY, AVERAGE_VOLUME)
    assert holds(compare(indicator("ind_v"), "eq", 2160), VOLUME_DAY, AVERAGE_VOLUME), "with the latest bar: (50000 - 1000 + 5000)/25"


@pytest.mark.parametrize(
    "condition",
    [
        compare(VOLUME, "eq", 5000),
        compare(VOLUME, "gt", arithmetic(indicator("ind_v", bars_ago=1), "multiply", 2.4)),
        compare(VOLUME, "gte", arithmetic(indicator("ind_v", bars_ago=1), "multiply", 2.5)),
        compare(arithmetic(VOLUME, "divide", indicator("ind_v", bars_ago=1)), "eq", 2.5),
    ],
    ids=["shares", "over-2.4x", "at-2.5x", "ratio"],
)
def test_todays_volume_in_shares_against_a_multiple_of_the_previous_average(condition: Json) -> None:
    assert holds(condition, VOLUME_DAY, AVERAGE_VOLUME)


def test_todays_volume_at_a_multiple_is_not_above_it() -> None:
    assert not holds(compare(VOLUME, "gt", arithmetic(indicator("ind_v", bars_ago=1), "multiply", 2.5)), VOLUME_DAY, AVERAGE_VOLUME)


# ----------------------------------- Scoring ----------------------------------- #

THREE_HOLDING = group("all", compare(CLOSE, "gt", 1), compare(CLOSE, "gt", 2), compare(CLOSE, "gt", 3))
THREE_FAILING = group("any", compare(CLOSE, "lt", 1), compare(CLOSE, "lt", 2), compare(CLOSE, "lt", 3))
SCORING = {"base_score": 60, "block_failure_penalty": 20, "failure_score_reduction": 7, "pass_score_increase": 4}


@pytest.mark.parametrize(
    ("effect", "condition", "report"),
    [
        ("block_on_fail", THREE_FAILING, TechnicalReport(score=40, hard_failures=["Rule"])),
        ("block_on_fail", THREE_HOLDING, TechnicalReport(score=60)),
        ("reduce_score_on_fail", THREE_FAILING, TechnicalReport(score=53, soft_failures=["Rule"])),
        ("reduce_score_on_fail", THREE_HOLDING, TechnicalReport(score=60)),
        ("increase_score_on_pass", THREE_HOLDING, TechnicalReport(score=64, observations=["Rule: detected"])),
        ("increase_score_on_pass", THREE_FAILING, TechnicalReport(score=60, observations=["Rule: not detected"])),
    ],
    ids=["block-failed", "block-passed", "reduce-failed", "reduce-passed", "increase-passed", "increase-failed"],
)
def test_a_rules_effect_applies_once_however_many_conditions_it_holds(effect: str, condition: Json, report: TechnicalReport) -> None:
    assert strategy(rule("Rule", condition, effect), scoring=SCORING).apply(stock(TWELVE_AFTER_EIGHT)) == report


def test_failures_and_bonuses_of_several_rules_add_up() -> None:
    rules = (
        rule("Blocks", THREE_FAILING),
        rule("Reduces", THREE_FAILING, "reduce_score_on_fail"),
        rule("Adds", THREE_HOLDING, "increase_score_on_pass"),
        rule("Passes", THREE_HOLDING),
    )

    assert strategy(*rules, scoring=SCORING).apply(stock(TWELVE_AFTER_EIGHT)) == TechnicalReport(
        score=37, hard_failures=["Blocks"], soft_failures=["Reduces"], observations=["Adds: detected"]
    )


@pytest.mark.parametrize(
    ("scoring", "effect", "condition", "score"),
    [
        ({"base_score": 95, "pass_score_increase": 10}, "increase_score_on_pass", THREE_HOLDING, 100),
        ({"base_score": 10, "block_failure_penalty": 15}, "block_on_fail", THREE_FAILING, 0),
    ],
    ids=["bonuses-past-100", "penalties-past-0"],
)
def test_the_score_stays_between_0_and_100(scoring: Json, effect: str, condition: Json, score: int) -> None:
    probe = strategy(rule("First", condition, effect), rule("Second", condition, effect), scoring=scoring)

    assert probe.apply(stock(TWELVE_AFTER_EIGHT)).score == score
