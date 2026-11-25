"""
The backtest's daily bars as one matrix of stocks by sessions, and the windows StrategyScoresRule scores on it: each
cell is what TechnicalStrategy.apply reports on the stock's bars of that session's window.
"""

from datetime import date, datetime, time, timedelta

import numpy as np
import pytest
from pydantic import TypeAdapter, ValidationError
from support.formulas import LATEST_PRICE, compare, indicator, market, rule
from support.settings import shipped_config

from a_domain.model.market.ohlcv import Ohlcv
from a_domain.model.market.stock import Stock
from a_domain.rules.technical.matrix import DailyBarMatrix, DailyBarMatrixRule, StrategyScoresRule
from a_domain.rules.technical.strategy import TechnicalStrategy
from c_infrastructure.system.market_clock import TAIWAN_TIMEZONE

SEVERAL_KINDS = TypeAdapter(TechnicalStrategy).validate_python(
    {
        "strategy_id": "several_kinds",
        "name": "Several kinds",
        "indicators": {
            "ind_a": {"kind": "sma", "period": 3},
            "ind_b": {"kind": "rsi", "period": 4},
            "ind_c": {"kind": "macd", "fast": 2, "slow": 5, "signal": 3},
            "ind_d": {"kind": "bollinger", "period": 5, "std": 1.0},
            "ind_e": {"kind": "stochastic", "k_period": 4, "d_period": 2},
            "ind_f": {"kind": "adx", "period": 3},
            "ind_g": {"kind": "obv", "period": 4},
        },
        "scoring": {"base_score": 50, "pass_score_increase": 7},
        "rules": [
            rule("Above its average", compare(LATEST_PRICE, "gt", indicator("ind_a"))),
            rule("Strong", compare(indicator("ind_b"), "gte", 50), "reduce_score_on_fail"),
            rule(
                "MACD over its signal",
                compare(indicator("ind_c", "line"), "gt", indicator("ind_c", "signal")),
                "increase_score_on_pass",
            ),
            rule("Under the band", compare(market("close", 1), "lt", indicator("ind_d", "upper", 1)), "increase_score_on_pass"),
            rule("K over D", compare(indicator("ind_e", "percent_k"), "gt", indicator("ind_e", "percent_d")), "reduce_score_on_fail"),
            rule("Trending", compare(indicator("ind_f", "adx"), "gt", 25), "increase_score_on_pass"),
            rule("Volume confirms", compare(indicator("ind_g"), "gt", indicator("ind_g", "moving_average")), "increase_score_on_pass"),
        ],
    }
)


def daily_bars() -> DailyBarMatrix:
    """
    Three random walks over 100 sessions a day apart. The second misses a session, and the third lists at the 30th,
    so its first windows, like every stock's at the start, hold fewer bars than a strategy needs.
    """
    generator = np.random.default_rng(11)
    shape = (3, 100)
    close = np.round(100 * np.cumprod(1 + generator.normal(0.002, 0.02, shape), axis=1), 2)
    spread = close * generator.uniform(0.005, 0.04, shape)
    high, low = np.round(close + spread, 2), np.round(close - spread, 2)
    fields = {"open": np.round(generator.uniform(low, high), 2), "high": high, "low": low, "close": close}
    fields["volume"] = np.round(10 ** generator.uniform(3, 6, shape))
    missing = np.zeros(shape, dtype=np.bool_)
    missing[1, 50], missing[2, :30] = True, True
    return DailyBarMatrix(
        stock_ids=("2330", "2454", "6669"),
        sessions=tuple(date(2026, 1, 5) + timedelta(days=day) for day in range(100)),
        **{name: np.where(missing, np.nan, values) for name, values in fields.items()},
    )


def bar(bars: DailyBarMatrix, stock: int, session: int) -> Ohlcv:
    return Ohlcv(
        ts=datetime.combine(bars.sessions[session], time(13, 30), TAIWAN_TIMEZONE),
        **{name: float(getattr(bars, name)[stock, session]) for name in ("open", "high", "low", "close")},
        volume=int(bars.volume[stock, session]),
    )


@pytest.mark.parametrize(
    "strategy", [shipped_config().technical.built_in_strategies[0], SEVERAL_KINDS], ids=lambda strategy: strategy.strategy_id
)
def test_every_cell_scores_as_the_strategy_scores_the_stocks_bars_of_that_sessions_window(strategy: TechnicalStrategy) -> None:
    bars = daily_bars()
    starts = [max(0, session - strategy.required_bars - 9) for session in range(len(bars.sessions))]
    scores = StrategyScoresRule(strategy).apply(bars, starts)
    wrong, short, scored = [], [], set()

    for stock, session in np.argwhere(~np.isnan(bars.close)):
        window = [
            bar(bars, stock, column) for column in range(starts[session], session + 1) if not np.isnan(bars.close[stock, column])
        ]
        [report] = strategy.apply([Stock(stock_id=bars.stock_ids[stock], ohlcv=window)])

        if (scores.score[stock, session], scores.passed[stock, session]) != (report.score, report.passed):
            wrong.append((int(stock), int(session), report.score, int(scores.score[stock, session])))

        if len(window) < strategy.required_bars:
            short.append((stock, session))
        else:
            scored.add(report.score)

    assert wrong == [], "(stock, session, apply's score, the backtest's)"
    assert short and all(scores.score[cell] == 0 and not scores.passed[cell] for cell in short)
    assert len(scored) > 3, "the windows long enough score apart"
    assert not scores.score[np.isnan(bars.close)].any() and not scores.passed[np.isnan(bars.close)].any()


def test_a_window_that_starts_after_its_session_is_refused() -> None:
    strategy = shipped_config().technical.built_in_strategies[0]
    sessions = tuple(date(2026, 1, 5) + timedelta(days=day) for day in range(40))
    bars = DailyBarMatrix(
        stock_ids=("2330",), sessions=sessions, **{name: np.ones((1, 40)) for name in ("open", "high", "low", "close", "volume")}
    )

    with pytest.raises(ValueError, match="window_starts"):
        StrategyScoresRule(strategy).apply(bars, [*range(39), 40])


def test_a_bar_without_every_field_is_refused() -> None:
    fields = {name: np.ones((1, 2)) for name in ("open", "high", "low", "close", "volume")}
    fields["volume"][0, 1] = np.nan

    with pytest.raises(ValidationError, match="every field"):
        DailyBarMatrix(stock_ids=("2330",), sessions=(date(2026, 1, 5), date(2026, 1, 6)), **fields)


def test_daily_bars_become_one_matrix_with_a_gap_where_a_stock_has_no_bar() -> None:
    sessions = (date(2026, 3, 2), date(2026, 3, 3), date(2026, 3, 4))

    def bar(column: int, close: float) -> Ohlcv:
        stamp = datetime.combine(sessions[column], time(13, 30), TAIWAN_TIMEZONE)
        return Ohlcv(ts=stamp, open=close - 1, high=close + 1, low=close - 2, close=close, volume=500)

    history = {"2454": [bar(0, 50), bar(2, 52)], "2330": [bar(1, 101), bar(2, 102)]}
    bars = DailyBarMatrixRule().apply(history, lambda stamp: stamp.astimezone(TAIWAN_TIMEZONE).date())

    assert (bars.stock_ids, bars.sessions) == (("2330", "2454"), sessions)
    assert np.array_equal(bars.close, [[np.nan, 101, 102], [50, np.nan, 52]], equal_nan=True)
    assert np.array_equal(bars.open, [[np.nan, 100, 101], [49, np.nan, 51]], equal_nan=True)
    assert np.array_equal(bars.volume, [[np.nan, 500, 500], [500, np.nan, 500]], equal_nan=True)
