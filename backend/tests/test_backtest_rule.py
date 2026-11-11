"""
The replay of a backtest on hand-built bars where the right answer is plain: when a decision fills and at what price,
what a locked limit and a missing bar do, who gets the cash when it runs out, and that no decision reads a later bar.
"""

from dataclasses import replace
from datetime import date, datetime, time, timedelta

import numpy as np
import pytest
from support.trading_rules import COSTS, EXIT_REASON, run_decisions_rule

from a_domain.model.market.ohlcv import Ohlcv
from a_domain.model.trading.account import Account
from a_domain.model.trading.backtest import BacktestTrade
from a_domain.rules.technical.matrix import DailyBarMatrix, StrategyScores
from a_domain.rules.trading.account_value import PositionValueRule
from a_domain.rules.trading.backtest import (
    BacktestHistoryRule,
    BacktestPeriodRule,
    BacktestRule,
    DailyBarMatrixRule,
    OpenFillRule,
    SessionStopLossRule,
)
from a_domain.rules.trading.cost import AffordableQuantityRule
from a_domain.rules.trading.exit import StopLossRule
from a_domain.types.enums import SignalSource, TradeAction
from a_domain.types.errors import BacktestPeriodUnavailable
from c_infrastructure.system.market_clock import TAIWAN_TIMEZONE

FIRST = date(2026, 3, 2)
CASH = 1_000_000.0
HOLD, BUY, SELL = 50, 80, 20
"""Scores between the thresholds, at the buy threshold and below the sell threshold of backtest_rule()."""

type Bar = tuple[float, float, float, float] | None
"""(open, high, low, close), or None for a session the stock did not trade."""


def flat(price: float) -> Bar:
    """A session that opens and closes at `price` and trades a little around it, so it is no locked limit."""
    return price, price + 1, price - 1, price


def locked(price: float) -> Bar:
    return price, price, price, price


def session(column: int) -> date:
    return FIRST + timedelta(days=column)


def session_close(day: date) -> datetime:
    return datetime.combine(day, time(13, 30), TAIWAN_TIMEZONE)


def matrix(bars: dict[str, list[Bar]]) -> DailyBarMatrix:
    cells = np.array([[bar or (np.nan,) * 4 for bar in row] for row in bars.values()], dtype=float)
    sessions = tuple(session(column) for column in range(cells.shape[1]))
    volume = np.where(np.isnan(cells[:, :, 3]), np.nan, 1000.0)

    return DailyBarMatrix(
        stock_ids=tuple(bars),
        sessions=sessions,
        open=cells[:, :, 0],
        high=cells[:, :, 1],
        low=cells[:, :, 2],
        close=cells[:, :, 3],
        volume=volume,
    )


def scored(scores: dict[str, list[int]], failed: dict[str, list[int]] | None = None) -> StrategyScores:
    """Every stock passes the strategy on every session, but on the columns `failed` names."""
    score = np.array(list(scores.values()))
    passed = np.ones(score.shape, dtype=bool)

    for row, stock_id in enumerate(scores):
        passed[row, (failed or {}).get(stock_id, [])] = False

    return StrategyScores(score=score, passed=passed)


def backtest_rule(risk_per_trade_pct: float = 0.02, lot_size: int = 1) -> BacktestRule:
    """Buys at 80 and sells at 20, with a stop-loss 10% below the average cost."""
    return BacktestRule(
        buy_score=BUY,
        run_decisions_rule=run_decisions_rule(risk_per_trade_pct, buy_threshold=BUY, sell_threshold=SELL),
        open_fill_rule=OpenFillRule(lot_size=lot_size, affordable_quantity_rule=AffordableQuantityRule(cost_rule=COSTS)),
        session_stop_loss_rule=SessionStopLossRule(stop_loss_rule=StopLossRule(stop_loss_pct=0.10, reason_rule=EXIT_REASON)),
        cost_rule=COSTS,
        position_value_rule=PositionValueRule(cost_rule=COSTS),
    )


def replay(
    bars: dict[str, list[Bar]],
    scores: dict[str, list[int]],
    *,
    cash: float = CASH,
    first: date = FIRST,
    rule: BacktestRule | None = None,
    failed: dict[str, list[int]] | None = None,
) -> tuple[dict[date, Account], list[BacktestTrade]]:
    names = {stock_id: f"Stock {stock_id}" for stock_id in bars}
    return (rule or backtest_rule()).apply(matrix(bars), scored(scores, failed), names, first, cash, session_close)


def bought_at(price: float, quantity: int) -> tuple[float, int]:
    """What a BUY of `quantity` shares at `price` costs, and its fee."""
    cost = COSTS.apply(TradeAction.BUY, "2330", price, quantity, now=session_close(FIRST))
    return -cost.net, cost.fee


def test_a_buy_decided_at_a_close_fills_at_the_next_open_and_stays_open_at_the_end() -> None:
    """2% of 1,000,000 at risk, 10% of the 90 close per share: 2,222 shares, bought at the next open of 100."""
    curve, trades = replay({"2330": [flat(90), (100, 104, 99, 102), flat(105)]}, {"2330": [BUY, HOLD, HOLD]})

    paid, fee = bought_at(100, 2222)
    sale = COSTS.apply(TradeAction.SELL, "2330", 105, 2222, now=session_close(session(2)))

    assert [account.cash for account in curve.values()] == [CASH, CASH - paid, CASH - paid]
    assert curve[session(0)].positions == []
    assert curve[session(1)].equity == CASH - paid + 2222 * 102
    assert trades == [
        BacktestTrade(
            stock_id="2330",
            stock_name="Stock 2330",
            quantity=2222,
            bought_on=session(1),
            average_cost=paid / 2222,
            pnl=sale.net - paid,
            fee=fee,
            tax=0,
            held_sessions=1,
        )
    ]
    assert curve[session(2)].unrealized_pnl == trades[0].pnl


def test_a_stock_that_gaps_below_its_stop_loss_sells_at_the_open() -> None:
    curve, trades = replay({"2330": [flat(90), flat(100), (80, 82, 78, 81), flat(81)]}, {"2330": [BUY, HOLD, HOLD, HOLD]})

    paid, fee = bought_at(100, 2222)
    sale = COSTS.apply(TradeAction.SELL, "2330", 80, 2222, now=session_close(session(2)))
    [trade] = trades

    assert (trade.sold_on, trade.sold_at, trade.exit_source) == (session(2), 80, SignalSource.STOP_LOSS)
    assert (trade.pnl, trade.fee, trade.tax, trade.held_sessions) == (sale.net - paid, fee + sale.fee, sale.tax, 1)
    assert curve[session(2)].positions == []
    assert curve[session(3)].cash == CASH - paid + sale.net


def test_a_stop_loss_reached_inside_the_session_sells_at_the_stop_loss_price() -> None:
    _, trades = replay({"2330": [flat(90), flat(100), (99, 99.5, 85, 95), flat(95)]}, {"2330": [BUY, HOLD, HOLD, HOLD]})

    paid, _ = bought_at(100, 2222)
    [trade] = trades

    assert trade.exit_source == SignalSource.STOP_LOSS
    assert trade.sold_at == pytest.approx(paid / 2222 * 0.9)
    assert 85 < trade.sold_at < 99


def test_a_low_above_the_stop_loss_sells_nothing() -> None:
    _, trades = replay({"2330": [flat(90), flat(100), (99, 99.5, 91, 95)]}, {"2330": [BUY, HOLD, HOLD]})

    assert [trade.sold_on for trade in trades] == [None]


def test_a_buy_is_dropped_on_a_locked_limit_and_is_not_tried_again() -> None:
    curve, trades = replay({"2330": [flat(90), locked(99), flat(99)]}, {"2330": [BUY, HOLD, HOLD]})

    assert trades == []
    assert [account.equity for account in curve.values()] == [CASH, CASH, CASH]


def test_a_buy_is_dropped_when_the_stock_has_no_bar_at_the_next_session() -> None:
    _, trades = replay({"2330": [flat(90), None, flat(99)]}, {"2330": [BUY, 0, HOLD]})

    assert trades == []


def test_when_the_cash_runs_out_the_better_score_buys_and_a_tie_goes_to_the_lower_stock_id() -> None:
    """Each BUY wants 10% of 30,000 at risk, 10% of the 10 close per share: 3,000 shares, the whole cash."""
    bars = {stock_id: [flat(10), flat(10), flat(10)] for stock_id in ("3008", "2330", "2454")}
    scores = {"3008": [90, HOLD, HOLD], "2330": [90, HOLD, HOLD], "2454": [95, HOLD, HOLD]}

    _, trades = replay(bars, scores, cash=30_000, rule=backtest_rule(risk_per_trade_pct=0.10))

    assert [(trade.stock_id, trade.quantity) for trade in trades] == [("2454", 2995)]

    _, tied = replay(bars, scores | {"2454": [HOLD, HOLD, HOLD]}, cash=30_000, rule=backtest_rule(risk_per_trade_pct=0.10))

    assert [(trade.stock_id, trade.quantity) for trade in tied] == [("2330", 2995)]


def test_a_buy_takes_only_the_shares_the_cash_pays_for_at_the_open() -> None:
    """Decided at the close of 10 for 2,995 shares; at the open of 11 the cash of 30,000 pays for 2,723, fee included."""
    curve, trades = replay(
        {"2330": [flat(10), flat(11), flat(11)]}, {"2330": [BUY, HOLD, HOLD]}, cash=30_000, rule=backtest_rule(0.10)
    )

    paid, _ = bought_at(11, 2723)

    assert [trade.quantity for trade in trades] == [2723]
    assert curve[session(1)].cash == pytest.approx(30_000 - paid)
    assert bought_at(11, 2724)[0] > 30_000


def test_a_sale_that_costs_more_than_it_brings_does_not_fill_on_an_account_without_the_cash() -> None:
    """
    30.02 buys one share at 10 with the minimum fee of 20, so the share cost 30 and its stop-loss is 27, above its
    price: selling it would bring 10 and cost a fee of 20, which the 0.02 left cannot pay.
    """
    curve, trades = replay({"2330": [flat(10), flat(10), flat(10)]}, {"2330": [BUY, HOLD, HOLD]}, cash=30.02, rule=backtest_rule(0.10))

    [trade] = trades

    assert (trade.quantity, trade.average_cost, trade.sold_on, trade.pnl) == (1, 30, None, -40)
    assert [round(account.cash, 2) for account in curve.values()] == [30.02, 0.02, 0.02]


def test_a_score_at_the_sell_threshold_sells_at_the_next_open() -> None:
    _, trades = replay({"2330": [flat(90), flat(100), flat(104), flat(106), flat(108)]}, {"2330": [BUY, HOLD, SELL, HOLD, HOLD]})

    [trade] = trades

    assert (trade.sold_on, trade.sold_at, trade.exit_source, trade.held_sessions) == (session(3), 106, SignalSource.COMBINED, 2)
    assert trade.pnl > 0
    assert trade.return_pct == pytest.approx(trade.pnl / (2222 * trade.average_cost))


def test_a_sell_waits_while_the_stock_has_no_bar_or_is_locked_below_its_previous_close() -> None:
    bars = {"2330": [flat(90), flat(100), flat(104), None, locked(95), flat(96), flat(96)]}

    curve, trades = replay(bars, {"2330": [BUY, HOLD, SELL, 0, HOLD, HOLD, HOLD]})
    [trade] = trades

    assert (trade.sold_on, trade.sold_at, trade.exit_source) == (session(5), 96, SignalSource.COMBINED)
    assert [len(curve[session(column)].positions) for column in range(2, 6)] == [1, 1, 1, 0]
    assert curve[session(3)].positions[0].mark_price == 104


def test_a_sell_fills_on_a_bar_locked_above_its_previous_close() -> None:
    _, trades = replay({"2330": [flat(90), flat(100), flat(104), locked(114), flat(114)]}, {"2330": [BUY, HOLD, SELL, HOLD, HOLD]})

    assert [(trade.sold_on, trade.sold_at) for trade in trades] == [(session(3), 114)]


def test_a_stock_that_failed_the_strategy_is_not_bought_and_a_held_one_at_the_sell_score_is_sold() -> None:
    bars = {"2330": [flat(90), flat(100), flat(100), flat(100)], "2454": [flat(50), flat(50), flat(50), flat(50)]}
    scores = {"2330": [BUY, SELL, HOLD, HOLD], "2454": [95, 95, 95, 95]}

    _, trades = replay(bars, scores, failed={"2330": [1], "2454": [0, 1, 2, 3]})

    assert [(trade.stock_id, trade.sold_on, trade.exit_source) for trade in trades] == [("2330", session(2), SignalSource.COMBINED)]


def test_without_a_score_at_the_buy_threshold_nothing_trades() -> None:
    curve, trades = replay(
        {"2330": [flat(90), flat(100), flat(80)], "2454": [flat(50), None, flat(40)]}, {"2330": [79, 79, 79], "2454": [0, 0, 0]}
    )

    assert trades == []
    assert [(account.cash, account.equity) for account in curve.values()] == [(CASH, CASH)] * 3


def test_the_sessions_before_the_first_day_are_history_only() -> None:
    curve, trades = replay({"2330": [flat(90), flat(100), flat(100), flat(100)]}, {"2330": [BUY, HOLD, HOLD, HOLD]}, first=session(1))

    assert list(curve) == [session(1), session(2), session(3)]
    assert trades == []


def test_the_last_session_decides_nothing() -> None:
    _, trades = replay({"2330": [flat(90), flat(100)]}, {"2330": [HOLD, BUY]})

    assert trades == []


def busy_market() -> tuple[DailyBarMatrix, StrategyScores]:
    """Twelve stocks over forty sessions with gaps, falls and locked bars: BUYs, score SELLs and stop-losses all happen."""
    random = np.random.default_rng(7)
    closes = 100 * np.cumprod(1 + random.normal(0, 0.04, (12, 40)), axis=1)
    opens = closes * (1 + random.normal(0, 0.03, closes.shape))
    highs, lows = np.maximum(opens, closes) * 1.01, np.minimum(opens, closes) * 0.97
    locked_bars = random.random(closes.shape) < 0.05
    opens, highs, lows = (np.where(locked_bars, closes, cells) for cells in (opens, highs, lows))
    missing = random.random(closes.shape) < 0.05
    cells = [np.where(missing, np.nan, values) for values in (opens, highs, lows, closes, np.full(closes.shape, 1000.0))]
    score = np.where(missing, 0, random.choice([10, 50, 85, 95], closes.shape, p=[0.2, 0.4, 0.2, 0.2]))
    sessions = tuple(session(column) for column in range(40))
    stock_ids = tuple(str(2301 + row) for row in range(12))

    return DailyBarMatrix(stock_ids, sessions, *cells), StrategyScores(
        score=score, passed=(score > 0) & (random.random(closes.shape) < 0.9)
    )


def test_no_decision_reads_a_bar_after_its_session() -> None:
    """Whatever every later session holds, bars and scores alike, the account and the sales up to a session are the same."""
    bars, scores = busy_market()
    rule = backtest_rule(risk_per_trade_pct=0.05)
    curve, trades = rule.apply(bars, scores, {}, FIRST, CASH, session_close)

    assert {trade.exit_source for trade in trades} == {SignalSource.COMBINED, SignalSource.STOP_LOSS, None}

    for known in range(len(bars.sessions) - 1):
        later = slice(known + 1, None)
        other_bars = replace(bars, **{name: getattr(bars, name).copy() for name in ("open", "high", "low", "close", "volume")})

        for name, factor in (("open", 1.7), ("high", 1.7), ("low", 1.7), ("close", 1.7), ("volume", 1)):
            getattr(other_bars, name)[:, later] = getattr(bars, name)[:, later][::-1] * factor

        other_scores = StrategyScores(score=scores.score.copy(), passed=scores.passed.copy())
        other_scores.score[:, later], other_scores.passed[:, later] = 95, True
        other_curve, other_trades = rule.apply(other_bars, other_scores, {}, FIRST, CASH, session_close)
        until = bars.sessions[known]

        assert [other_curve[day] for day in bars.sessions[: known + 1]] == [curve[day] for day in bars.sessions[: known + 1]]
        assert [trade for trade in other_trades if trade.sold_on and trade.sold_on <= until] == [
            trade for trade in trades if trade.sold_on and trade.sold_on <= until
        ]


def test_the_account_never_spends_more_than_its_cash_and_every_sale_is_in_the_trades() -> None:
    bars, scores = busy_market()
    curve, trades = backtest_rule(risk_per_trade_pct=0.05).apply(bars, scores, {}, FIRST, CASH, session_close)
    last = curve[bars.sessions[-1]]
    realized = sum(trade.pnl for trade in trades if trade.sold_on)

    assert all(account.cash >= 0 for account in curve.values())
    assert last.cash + sum(position.cost_basis for position in last.positions) == pytest.approx(CASH + realized)
    assert sorted(trade.stock_id for trade in trades if trade.sold_on is None) == sorted(last.stock_ids)


# ---------------------------------------------------------------------------- #
#                         The period and the history                           #
# ---------------------------------------------------------------------------- #


def test_a_backtest_may_start_a_history_window_after_the_first_session_held() -> None:
    rule = BacktestPeriodRule()

    assert rule.apply(date(2026, 1, 5), date(2026, 6, 30), 120) == (date(2026, 5, 5), date(2026, 6, 30))
    assert rule.apply(date(2026, 1, 5), date(2026, 5, 5), 120) == (date(2026, 5, 5), date(2026, 5, 5))
    assert rule.apply(date(2026, 1, 5), date(2026, 5, 4), 120) is None


def weekday_bars(days: int) -> DailyBarMatrix:
    """One stock with a bar on every weekday from Monday 2026-03-02, its close the column number."""
    sessions = tuple(day for offset in range(days) if (day := FIRST + timedelta(days=offset)).weekday() < 5)
    cells = np.arange(len(sessions), dtype=float).reshape(1, -1)

    return DailyBarMatrix(("2330",), sessions, cells, cells, cells, cells, cells)


def test_the_history_of_a_period_starts_at_its_first_sessions_window_and_names_each_sessions_window() -> None:
    """A 7-day window: the period from Saturday 03-14 starts on Monday 03-16, whose window starts on Monday 03-09."""
    history, window_starts = BacktestHistoryRule(period_rule=BacktestPeriodRule()).apply(
        weekday_bars(28), date(2026, 3, 14), date(2026, 3, 18), 7
    )

    assert history.sessions == (date(2026, 3, 9), *(date(2026, 3, day) for day in (10, 11, 12, 13, 16, 17, 18)))
    assert history.close.tolist() == [[5, 6, 7, 8, 9, 10, 11, 12]]
    assert window_starts == [0, 0, 0, 0, 0, 0, 1, 2]


@pytest.mark.parametrize(
    ("first", "last", "refusal"),
    [
        (date(2026, 3, 8), date(2026, 3, 20), "can cover 2026-03-09 to 2026-03-27, and 2026-03-08 to 2026-03-20 reaches outside it"),
        (date(2026, 3, 16), date(2026, 3, 28), "can cover 2026-03-09 to 2026-03-27, and 2026-03-16 to 2026-03-28 reaches outside it"),
        (date(2026, 3, 14), date(2026, 3, 15), "2026-03-14 to 2026-03-15 holds no session"),
    ],
)
def test_a_period_the_history_cannot_replay_is_refused_with_what_it_can(first: date, last: date, refusal: str) -> None:
    with pytest.raises(BacktestPeriodUnavailable, match=refusal):
        BacktestHistoryRule(period_rule=BacktestPeriodRule()).apply(weekday_bars(28), first, last, 7)


def test_a_history_shorter_than_the_window_allows_no_backtest() -> None:
    with pytest.raises(BacktestPeriodUnavailable, match="No backtest can run yet: the daily history holds 2026-03-02 to 2026-03-06"):
        BacktestHistoryRule(period_rule=BacktestPeriodRule()).apply(weekday_bars(5), date(2026, 3, 4), date(2026, 3, 6), 7)


def test_daily_bars_become_one_matrix_with_a_gap_where_a_stock_has_no_bar() -> None:
    def bar(column: int, close: float) -> Ohlcv:
        return Ohlcv(ts=session_close(session(column)), open=close - 1, high=close + 1, low=close - 2, close=close, volume=500)

    history = {"2454": [bar(0, 50), bar(2, 52)], "2330": [bar(1, 101), bar(2, 102)]}
    bars = DailyBarMatrixRule().apply(history, lambda stamp: stamp.astimezone(TAIWAN_TIMEZONE).date())

    assert (bars.stock_ids, bars.sessions) == (("2330", "2454"), (session(0), session(1), session(2)))
    assert np.array_equal(bars.close, [[np.nan, 101, 102], [50, np.nan, 52]], equal_nan=True)
    assert np.array_equal(bars.open, [[np.nan, 100, 101], [49, np.nan, 51]], equal_nan=True)
    assert np.array_equal(bars.volume, [[np.nan, 500, 500], [500, np.nan, 500]], equal_nan=True)
