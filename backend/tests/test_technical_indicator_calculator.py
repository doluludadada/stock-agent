"""Indicator math at the latest of the bars given, with each expected value worked out by hand from its definition."""

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import TypeAdapter

from a_domain.model.market.ohlcv import Ohlcv
from a_domain.rules.technical.calculation.calculator import IndicatorParameters, indicator_outputs, indicator_series
from a_domain.types.enums import IndicatorKind, IndicatorOutput

PARAMETERS = TypeAdapter(IndicatorParameters)
FIRST_SESSION = datetime(2026, 1, 5, 13, 30, tzinfo=UTC)


def bars(*rows: tuple[float, float, float, int]) -> list[Ohlcv]:
    """One bar per (high, low, close, volume), a trading day apart."""
    return [
        Ohlcv(ts=FIRST_SESSION + timedelta(days=day), open=close, high=high, low=low, close=close, volume=volume)
        for day, (high, low, close, volume) in enumerate(rows)
    ]


def closes(*values: float, volumes: tuple[int, ...] | None = None) -> list[Ohlcv]:
    return bars(*((value, value, value, volume) for value, volume in zip(values, volumes or (1000,) * len(values), strict=True)))


def outputs(parameters: dict[str, object], history: list[Ohlcv]) -> dict[IndicatorOutput, float]:
    return indicator_outputs(PARAMETERS.validate_python(parameters), history)


V, LINE, SIGNAL, HISTOGRAM = IndicatorOutput.VALUE, IndicatorOutput.LINE, IndicatorOutput.SIGNAL, IndicatorOutput.HISTOGRAM


def test_sma_averages_the_last_period_closes() -> None:
    assert outputs({"kind": "sma", "period": 4}, closes(*range(1, 11))) == {V: 8.5}


def test_volume_sma_averages_the_last_period_volumes_in_shares() -> None:
    assert outputs({"kind": "volume_sma", "period": 3}, closes(10, 10, 10, 10, volumes=(9000, 100, 200, 600))) == {V: 300}


@pytest.mark.parametrize(
    ("history", "rsi"),
    [
        (closes(10, 11, 12, 13), 100),
        (closes(13, 12, 11, 10), 0),
        (closes(10, 10, 10, 10), 50),
        (closes(10, 11, 10, 12), 75),
        (closes(10, 11, 10, 12, 11), 100 - 100 / 2.2),
    ],
    ids=["only-gains", "only-losses", "flat", "gains-3-losses-1", "wilder-smoothed"],
)
def test_rsi_relates_average_gain_to_average_loss(history: list[Ohlcv], rsi: float) -> None:
    """The smoothed case: gains average (1 x 2 + 0)/3 = 2/3 and losses (1/3 x 2 + 1)/3 = 5/9, so RS = 1.2."""
    assert outputs({"kind": "rsi", "period": 3}, history) == {V: pytest.approx(rsi)}


def test_macd_line_signal_and_histogram_after_a_jump() -> None:
    """Every EMA is 100 before the jump to 120, after which an n-bar EMA is 100 + 20 x 2/(n+1)."""
    line = 20 * (2 / 13 - 2 / 27)

    assert outputs({"kind": "macd", "fast": 12, "slow": 26, "signal": 9}, closes(*[100] * 39, 120)) == {
        LINE: pytest.approx(line),
        SIGNAL: pytest.approx(line * 2 / 10),
        HISTOGRAM: pytest.approx(line * 8 / 10),
    }


def test_bollinger_bands_use_the_population_deviation_of_the_window() -> None:
    """The window 3, 4, 5, 6 has mean 4.5 and deviation sqrt(1.25)."""
    deviation = 1.25**0.5
    upper, lower = 4.5 + 2 * deviation, 4.5 - 2 * deviation

    assert outputs({"kind": "bollinger", "period": 4, "std": 2.0}, closes(1, 2, 3, 4, 5, 6)) == {
        IndicatorOutput.UPPER: pytest.approx(upper),
        IndicatorOutput.MIDDLE: pytest.approx(4.5),
        IndicatorOutput.LOWER: pytest.approx(lower),
        IndicatorOutput.BANDWIDTH: pytest.approx((upper - lower) / 4.5),
        IndicatorOutput.PERCENT_B: pytest.approx((6 - lower) / (upper - lower)),
    }


def test_bollinger_bands_of_a_flat_price_meet_at_it() -> None:
    assert outputs({"kind": "bollinger", "period": 4, "std": 2.0}, closes(7, 7, 7, 7)) == {
        IndicatorOutput.UPPER: 7,
        IndicatorOutput.MIDDLE: 7,
        IndicatorOutput.LOWER: 7,
        IndicatorOutput.BANDWIDTH: 0,
        IndicatorOutput.PERCENT_B: 0.5,
    }


def test_stochastic_k_places_the_close_in_the_recent_range_and_d_averages_k() -> None:
    """%K is 80 on the third bar, (12 - 8)/(13 - 8), and 40 on the fourth, (11 - 9)/(14 - 9)."""
    history = bars((10, 8, 9, 1000), (12, 9, 11, 1000), (13, 10, 12, 1000), (14, 11, 11, 1000))

    assert outputs({"kind": "stochastic", "k_period": 3, "d_period": 2}, history) == {
        IndicatorOutput.PERCENT_K: pytest.approx(40),
        IndicatorOutput.PERCENT_D: pytest.approx(60),
    }


def test_atr_smooths_the_true_ranges_including_a_gap_from_the_previous_close() -> None:
    """True ranges 3, 3 and, after a gap up from 12 to a 18-20 bar, 20 - 12 = 8: (3 + 3)/2 = 3, then (3 + 8)/2."""
    history = bars((10, 8, 9, 1000), (12, 9, 11, 1000), (13, 10, 12, 1000), (20, 18, 19, 1000))

    assert outputs({"kind": "atr", "period": 2}, history) == {V: 5.5}


def test_obv_adds_volume_on_up_closes_subtracts_it_on_down_closes_and_averages_itself() -> None:
    """OBV runs 0, 200, -100, -100, 400; its 3-bar average is (-100 - 100 + 400)/3."""
    history = closes(10, 11, 10, 10, 12, volumes=(100, 200, 300, 400, 500))

    assert outputs({"kind": "obv", "period": 3}, history) == {V: 400, IndicatorOutput.MOVING_AVERAGE: pytest.approx(200 / 3)}


@pytest.mark.parametrize(
    ("history", "mfi"),
    [(closes(10, 12, 11, volumes=(100, 200, 300)), 100 - 100 / (1 + 2400 / 3300)), (closes(10, 11, 12, volumes=(100, 200, 300)), 100)],
    ids=["flow-up-2400-down-3300", "only-rising"],
)
def test_mfi_relates_money_flowing_in_to_money_flowing_out(history: list[Ohlcv], mfi: float) -> None:
    assert outputs({"kind": "mfi", "period": 2}, history) == {V: pytest.approx(mfi)}


@pytest.mark.parametrize(
    ("step", "adx", "plus_di", "minus_di"), [(1, 100, 50, 0), (-1, 100, 0, 50)], ids=["steady-rise", "steady-fall"]
)
def test_adx_of_a_steady_trend_is_100_with_the_trends_direction_at_half_the_true_range(
    step: int, adx: float, plus_di: float, minus_di: float
) -> None:
    """Each bar moves its 2-wide range by 1, so the directional movement is 1 of every true range of 2."""
    history = bars(*((10 + step * day + 1, 10 + step * day - 1, 10 + step * day, 1000) for day in range(6)))

    assert outputs({"kind": "adx", "period": 2}, history) == {
        IndicatorOutput.ADX: pytest.approx(adx),
        IndicatorOutput.PLUS_DI: pytest.approx(plus_di),
        IndicatorOutput.MINUS_DI: pytest.approx(minus_di),
    }


EVERY_KIND = [
    ({"kind": "sma", "period": 5}, 5),
    ({"kind": "volume_sma", "period": 5}, 5),
    ({"kind": "rsi", "period": 14}, 15),
    ({"kind": "macd", "fast": 12, "slow": 26, "signal": 9}, 34),
    ({"kind": "bollinger", "period": 20, "std": 2.0}, 20),
    ({"kind": "stochastic", "k_period": 9, "d_period": 3}, 11),
    ({"kind": "adx", "period": 14}, 28),
    ({"kind": "atr", "period": 14}, 15),
    ({"kind": "obv", "period": 20}, 20),
    ({"kind": "mfi", "period": 14}, 15),
]


def wavy_history(count: int) -> list[Ohlcv]:
    return bars(*((101 + day % 4, 99 - day % 3, 100 + day % 5, 1000 + 10 * day) for day in range(count)))


def test_every_indicator_kind_is_covered() -> None:
    assert {parameters["kind"] for parameters, _ in EVERY_KIND} == set(IndicatorKind)


@pytest.mark.parametrize(("parameters", "required_bars"), EVERY_KIND, ids=[str(parameters["kind"]) for parameters, _ in EVERY_KIND])
def test_each_kind_gives_all_its_outputs_from_required_bars_and_none_from_fewer(
    parameters: dict[str, object], required_bars: int
) -> None:
    indicator = PARAMETERS.validate_python(parameters)

    assert indicator.required_bars == required_bars
    assert set(indicator_outputs(indicator, wavy_history(required_bars))) == set(indicator.kind.outputs)
    assert indicator_outputs(indicator, wavy_history(required_bars - 1)) == {}


@pytest.mark.parametrize(("parameters", "required_bars"), EVERY_KIND, ids=[str(parameters["kind"]) for parameters, _ in EVERY_KIND])
def test_each_kinds_series_holds_at_each_bar_exactly_its_outputs_over_the_bars_up_to_that_bar(
    parameters: dict[str, object], required_bars: int
) -> None:
    indicator = PARAMETERS.validate_python(parameters)
    history = [*wavy_history(required_bars * 3), *closes(120, 120, 120, 80, volumes=(0, 0, 5000, 0))]

    series = indicator_series(indicator, history)

    assert series == [indicator_outputs(indicator, history[:end]) for end in range(1, len(history) + 1)]
    assert series[required_bars - 2] == {} and set(series[required_bars - 1]) == set(indicator.kind.outputs)


def test_an_output_that_is_not_finite_is_absent() -> None:
    assert outputs({"kind": "sma", "period": 2}, closes(1e308, 1e308)) == {}
