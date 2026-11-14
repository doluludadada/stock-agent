"""
The monthly ranking's rules on small hand-made histories: the decision sessions and the revenue month each reads, the
total return of a bar and its level, the ranks, the universe, the two factors and the score, and the replay of the
ranking on weights with its costs, its locked opens and the stocks that do not trade.
"""

from datetime import date, datetime, time
from typing import Any

import numpy as np
import pytest

from a_domain.model.fundamentals.monthly_revenue import MonthlyRevenue
from a_domain.model.market.ohlcv import Ohlcv
from a_domain.rules.trading.ranking import (
    DecisionSessionsRule,
    ListedHistoryRule,
    MonthlyRankingRule,
    RankingHistory,
    RankingHistoryRule,
    ranks,
)
from a_domain.rules.trading.ranking_backtest import RankingBacktestRule, RankingPortfolioRule
from a_domain.types.enums import MarketType
from a_domain.types.errors import BacktestPeriodUnavailable
from c_infrastructure.system.market_clock import TAIWAN_TIMEZONE


def stamp(day: date) -> datetime:
    return datetime.combine(day, time(13, 30), tzinfo=TAIWAN_TIMEZONE)


def bar(day: date, close: float, change: float | None = None, *, open_price: float | None = None, volume: int = 1_000_000) -> Ohlcv:
    opened = close if open_price is None else open_price
    return Ohlcv(
        ts=stamp(day),
        open=opened,
        high=max(opened, close) + 0.5,
        low=min(opened, close) - 0.5,
        close=close,
        volume=volume,
        change=change,
    )


def revenue(stock_id: str, year: int, month: int, amount: float | None) -> MonthlyRevenue:
    return MonthlyRevenue(
        stock_id=stock_id,
        year=year,
        month=month,
        market=MarketType.TWSE,
        served_date=date(2026, 11, 10),
        company_name=stock_id,
        industry="",
        revenue=amount,
        previous_month_revenue=None,
        last_year_revenue=None,
        month_over_month_percent=None,
        year_over_year_percent=None,
        cumulative_revenue=None,
        last_year_cumulative_revenue=None,
        cumulative_year_over_year_percent=None,
        note="-",
    )


def history_of(bars: dict[str, list[Ohlcv]], revenues: list[MonthlyRevenue] | None = None, references: Any = None) -> RankingHistory:
    listed = ListedHistoryRule().apply(bars, references or {}, lambda moment: moment.date())
    held = {(item.stock_id, item.year, item.month): item.revenue for item in revenues or []}
    return RankingHistoryRule(daily_limit=0.105).apply(listed, held)


D = [date(2026, 3, day) for day in (2, 3, 4, 5, 6, 9, 10)]


def test_each_month_decides_at_its_first_session_on_the_decision_day_or_later_and_reads_the_revenue_due_before_it() -> None:
    sessions = [date(2026, 1, 12), date(2026, 1, 13), date(2026, 1, 14), date(2026, 2, 12), date(2026, 2, 16), date(2026, 2, 17)]

    assert DecisionSessionsRule(decision_day=13, deadline_day=10).apply(sessions) == [(1, date(2025, 12, 1)), (4, date(2026, 1, 1))]
    assert DecisionSessionsRule(decision_day=10, deadline_day=10).apply(sessions) == [(0, date(2025, 12, 1)), (3, date(2026, 1, 1))]
    assert DecisionSessionsRule(decision_day=5, deadline_day=10).apply([date(2026, 1, 6)]) == [(0, date(2025, 11, 1))]


def test_a_value_ranks_from_0_to_1_among_the_values_held_and_equal_values_share_their_mean_place() -> None:
    np.testing.assert_allclose(ranks(np.array([3.0, 1.0, np.nan, 2.0])), [1.0, 0.0, np.nan, 0.5])
    np.testing.assert_allclose(ranks(np.array([1.0, 1.0, 2.0, 1.0])), [1 / 3, 1 / 3, 1.0, 1 / 3])
    np.testing.assert_allclose(ranks(np.array([5.0, np.nan])), [np.nan, np.nan])


def test_a_bars_total_return_is_from_the_reference_it_was_compared_to_else_its_move_and_a_move_beyond_the_limit_is_0() -> None:
    bars = {
        "2330": [bar(D[0], 100.0), bar(D[1], 102.0, 2.0), bar(D[2], 97.0), bar(D[3], 99.0), bar(D[5], 120.0), bar(D[6], 120.0, 0.0)],
        "2317": [bar(D[1], 50.0), bar(D[2], 49.0)],
    }
    references = {"2330": {stamp(D[2]): 97.0, stamp(D[3]): 98.0}}

    history = history_of(bars, references=references)

    expected = [0.0, 2.0 / 100.0, 0.0, 99.0 / 98.0 - 1, 0.0, 0.0]
    assert history.bars.sessions == (D[0], D[1], D[2], D[3], D[5], D[6])
    np.testing.assert_allclose(history.returns[1], expected)
    np.testing.assert_allclose(history.level[1], np.cumprod(1 + np.array(expected)))
    np.testing.assert_allclose(history.returns[0], [0.0, 0.0, -0.02, 0.0, 0.0, 0.0])


def test_the_revenue_of_each_stock_is_in_its_row_by_month_and_a_month_without_one_is_nan() -> None:
    history = history_of(
        {"2330": [bar(D[0], 100.0)], "2317": [bar(D[0], 50.0)]},
        [
            revenue("2330", 2025, 11, 10.0),
            revenue("2317", 2026, 1, 7.0),
            revenue("2330", 2026, 1, None),
            revenue("9999", 2026, 2, 1.0),
        ],
    )

    assert history.months == (date(2025, 11, 1), date(2025, 12, 1), date(2026, 1, 1))
    np.testing.assert_allclose(history.revenue, [[np.nan, np.nan, 7.0], [10.0, np.nan, np.nan]])


RULE = MonthlyRankingRule(
    top=2, min_close=10, min_traded_value=1_000_000, traded_value_sessions=2, high_sessions=3, short_months=1, long_months=2
)


def ranked_market(listed_late: str | None = None) -> RankingHistory:
    """
    Four stocks and an ETF over three sessions, ranked at the last: 2330 at its high with revenue doubling, 2317 below
    its high with flat revenue, 1101 at its high with revenue halving, 2603 at its high without the revenue of the month
    before, 0050 an ETF at its high and 9910 trading too little to be in the universe. `listed_late` has no bar of the
    first session.
    """
    closes = {
        "2330": [100, 105, 110],
        "2317": [100, 120, 110],
        "1101": [20, 21, 22],
        "2603": [30, 31, 32],
        "0050": [50, 51, 52],
        "9910": [30, 31, 32],
    }
    bars = {
        stock_id: [bar(D[day], close, volume=10 if stock_id == "9910" else 1_000_000) for day, close in enumerate(prices)]
        for stock_id, prices in closes.items()
    }
    bars |= {stock_id: listed[1:] for stock_id, listed in bars.items() if stock_id == listed_late}
    revenues = [
        *(revenue(stock_id, 2026, 1, 100.0) for stock_id in ("2330", "2317", "1101", "0050", "9910")),
        revenue("2330", 2026, 2, 200.0),
        revenue("2317", 2026, 2, 100.0),
        revenue("1101", 2026, 2, 50.0),
        revenue("2603", 2026, 2, 80.0),
        revenue("0050", 2026, 2, 300.0),
        revenue("9910", 2026, 2, 300.0),
    ]
    return history_of(bars, revenues)


def test_the_ranking_ranks_its_universe_by_revenue_acceleration_and_nearness_to_the_high_and_holds_the_best() -> None:
    ranking = RULE.apply(ranked_market(), 2, date(2026, 2, 1), {"2330": "TSMC"})

    assert (ranking.decided_on, ranking.revenue_month, ranking.universe, ranking.scored) == (D[2], date(2026, 2, 1), 4, 3)
    assert [stock.stock_id for stock in ranking.stocks] == ["2330", "1101"]
    best = ranking.stocks[0]
    assert (best.stock_name, best.revenue_acceleration, best.nearness_to_high) == ("TSMC", 200 / 150, 1.0)
    assert (best.acceleration_rank, best.nearness_rank, best.score) == (1.0, pytest.approx(2 / 3), pytest.approx(5 / 3))
    assert (ranking.stocks[1].acceleration_rank, ranking.stocks[1].nearness_rank) == (0.0, pytest.approx(2 / 3))


def test_a_stock_listed_after_the_first_session_of_the_high_window_has_no_nearness_and_is_not_ranked() -> None:
    ranking = RULE.apply(ranked_market(listed_late="2330"), 2, date(2026, 2, 1), {})

    assert (ranking.universe, ranking.scored) == (4, 2)
    assert [stock.stock_id for stock in ranking.stocks] == ["1101", "2317"]


def test_a_history_too_short_for_a_factor_ranks_nothing() -> None:
    assert RULE.apply(ranked_market(), 1, date(2026, 2, 1), {}).stocks == []
    assert RULE.apply(ranked_market(), 2, date(2025, 12, 1), {}).scored == 0


REPLAY_RULE = RankingBacktestRule(
    decision_rule=DecisionSessionsRule(decision_day=3, deadline_day=1),
    ranking_rule=MonthlyRankingRule(
        top=2, min_close=0, min_traded_value=0, traded_value_sessions=1, high_sessions=1, short_months=1, long_months=2
    ),
    portfolio_rule=RankingPortfolioRule(fee_rate=0.001, tax_rate=0.003, benchmark_id="0050", sessions_per_year=245),
)
M = [date(2026, 3, 3), date(2026, 3, 4), date(2026, 3, 5), date(2026, 4, 3), date(2026, 4, 6), date(2026, 4, 7)]


def replay_market(locked: bool = False) -> RankingHistory:
    """
    Every stock is at its high, so revenue alone orders the rankings: 2330 and 2317 lead March's, 1101 and 2330 April's.
    2317 does not trade after its first April session, and 1101 opens on April 6 at its limit up with one price all day
    when `locked`.
    """
    bars = {
        "2330": [bar(day, close, open_price=close - 1) for day, close in zip(M, [100, 110, 121, 121, 110, 110], strict=True)],
        "2317": [bar(day, close, open_price=close) for day, close in zip(M[:4], [50, 55, 50, 50], strict=True)],
        "1101": [bar(day, 20.0, open_price=20.0) for day in M],
        "0050": [bar(day, close) for day, close in zip(M, [100, 101, 102, 103, 104, 105], strict=True)],
    }

    if locked:
        bars["1101"][4] = Ohlcv(ts=stamp(M[4]), open=22.0, high=22.0, low=22.0, close=22.0, volume=1000, change=2.0)

    revenues = [
        *(revenue(stock_id, 2026, 1, 100.0) for stock_id in ("2330", "2317", "1101")),
        *(revenue(stock_id, 2026, 2, amount) for stock_id, amount in (("2330", 300.0), ("2317", 200.0), ("1101", 100.0))),
        *(revenue(stock_id, 2026, 3, amount) for stock_id, amount in (("2330", 200.0), ("2317", 100.0), ("1101", 300.0))),
    ]
    return history_of(bars, revenues)


def test_the_replay_buys_each_ranking_at_the_next_open_in_equal_weights_and_pays_the_fee_and_the_tax() -> None:
    backtest = REPLAY_RULE.apply(replay_market(), {}, M[0], M[-1])

    assert [ranking.decided_on for ranking in backtest.rankings] == [M[0], M[3]]
    assert [stock.stock_id for stock in backtest.rankings[0].stocks] == ["2330", "2317"]
    assert backtest.holdings == {M[1]: ["2330", "2317"], M[4]: ["1101", "2330", "2317"]}
    after_buying = (1 - 0.001) * (1 + (110 / 109 - 1) / 2)
    assert backtest.equity_curve[M[0]] == 1.0
    assert backtest.equity_curve[M[1]] == pytest.approx(after_buying)
    assert list(backtest.benchmark_curve.values()) == pytest.approx([1.0, 1.01, 1.02, 1.03, 1.04, 1.05])
    assert backtest.costs > 0.001


def test_a_stock_that_opens_locked_without_being_held_is_not_bought_and_one_that_does_not_trade_is_not_sold() -> None:
    backtest = REPLAY_RULE.apply(replay_market(locked=True), {}, M[0], M[-1])

    assert backtest.holdings[M[4]] == ["2330", "2317"]
    unlocked = REPLAY_RULE.apply(replay_market(), {}, M[0], M[-1])
    assert unlocked.holdings[M[4]] == ["1101", "2330", "2317"]


def stuck_market(last_close: float = 80.0) -> RankingHistory:
    """
    March's ranking is 2330 and 2317, April's 1101 and 1216. On April 6, when April's is bought, neither of its stocks
    trades, and nor does 2330, so 2317 is sold and 2330 is left beside cash. 2330 trades again on April 7 at `last_close`.
    """
    flat = {stock_id: [bar(day, 100.0) for day in M] for stock_id in ("2317", "0050")}
    absent = {stock_id: [bar(day, 100.0) for day in M if day != M[4]] for stock_id in ("2330", "1101", "1216")}
    absent["2330"][-1] = bar(M[5], last_close, change=last_close - 100.0)
    revenues = [
        *(revenue(stock_id, 2026, 1, 100.0) for stock_id in ("2330", "2317", "1101", "1216")),
        *(
            revenue(stock_id, 2026, 2, amount)
            for stock_id, amount in (("2330", 300.0), ("2317", 200.0), ("1101", 100.0), ("1216", 100.0))
        ),
        *(
            revenue(stock_id, 2026, 3, amount)
            for stock_id, amount in (("2330", 100.0), ("2317", 100.0), ("1101", 300.0), ("1216", 250.0))
        ),
    ]
    return history_of(flat | absent, revenues)


def test_what_a_sale_frees_stays_cash_while_nothing_can_be_bought_so_a_stuck_holding_moves_only_its_own_share() -> None:
    backtest = REPLAY_RULE.apply(stuck_market(), {}, M[0], M[-1])

    assert backtest.holdings == {M[1]: ["2330", "2317"], M[4]: ["2330"]}
    half_sold = (1 - 0.001) * (1 - 0.5 * 0.004)
    assert backtest.equity_curve[M[4]] == pytest.approx(half_sold)
    assert backtest.equity_curve[M[5]] == pytest.approx(half_sold * (1 - 0.5 * 0.2))


def test_a_period_without_a_decision_session_is_refused_with_what_the_history_holds() -> None:
    with pytest.raises(BacktestPeriodUnavailable, match="2026-03-03 to 2026-04-07"):
        REPLAY_RULE.apply(replay_market(), {}, date(2026, 3, 10), date(2026, 3, 31))


def test_the_returns_compound_yearly_and_annually_over_the_sessions_after_the_first_decision() -> None:
    backtest = REPLAY_RULE.apply(replay_market(), {}, M[0], M[-1])
    values = list(backtest.equity_curve.values())

    assert backtest.total_return == pytest.approx(values[-1] - 1)
    assert backtest.annual_return == pytest.approx(values[-1] ** (245 / 5) - 1)
    assert backtest.yearly_returns == {2026: pytest.approx(values[-1] - 1)}
    assert backtest.max_drawdown == pytest.approx(max(1 - value / max(values[: index + 1]) for index, value in enumerate(values)))
