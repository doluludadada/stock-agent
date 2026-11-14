"""The stock page's financial analysis reads only what is held, and says so where the history is too short."""

from datetime import UTC, date, datetime, timedelta

import pytest

from a_domain.model.fundamentals.monthly_revenue import MonthlyRevenue
from a_domain.model.fundamentals.quarter_financials import QuarterFinancials
from a_domain.ports.market.daily_close_archive import ValuationRatios
from a_domain.rules.fundamentals.stock_analysis import (
    EarningsTrendRule,
    Reading,
    RevenueTrendRule,
    StockAnalysisRule,
    ValuationStandingRule,
)
from a_domain.rules.fundamentals.trailing_eps import QuarterEps
from a_domain.types.enums import MarketType, ReadingKind
from a_domain.types.values import FiscalQuarter

FETCHED = datetime(2026, 11, 1, tzinfo=UTC)
REVENUE_RULE = RevenueTrendRule(short_months=3, long_months=12)


def revenue(year: int, month: int, amount: float | None, year_over_year: float | None = None) -> MonthlyRevenue:
    return MonthlyRevenue(
        stock_id="2330",
        year=year,
        month=month,
        market=MarketType.TWSE,
        served_date=date(year + month // 12, month % 12 + 1, 10),
        company_name="TSMC",
        industry="",
        revenue=amount,
        previous_month_revenue=None,
        last_year_revenue=None,
        month_over_month_percent=None,
        year_over_year_percent=year_over_year,
        cumulative_revenue=None,
        last_year_cumulative_revenue=None,
        cumulative_year_over_year_percent=None,
        note="",
    )


def months(first: tuple[int, int], amounts: list[float | None]) -> list[MonthlyRevenue]:
    start = first[0] * 12 + first[1] - 1
    return [revenue((start + offset) // 12, (start + offset) % 12 + 1, amount) for offset, amount in enumerate(amounts)]


def ratios(day: date, pe_ratio: float | None, pb_ratio: float | None = 2.0) -> ValuationRatios:
    return ValuationRatios(stock_id="2330", session_date=day, pe_ratio=pe_ratio, dividend_yield=1.5, pb_ratio=pb_ratio)


def page(year: int, quarter: int, eps: float, stock_id: str = "2330") -> QuarterEps:
    return QuarterEps(quarter=FiscalQuarter(year, quarter), cumulative_eps={stock_id: eps}, fetched_at=FETCHED)


def analysis_rule(min_sessions: int = 3) -> StockAnalysisRule:
    return StockAnalysisRule(
        revenue_rule=REVENUE_RULE, earnings_rule=EarningsTrendRule(), valuation_rule=ValuationStandingRule(min_sessions=min_sessions)
    )


def test_the_acceleration_is_the_rankings_three_month_mean_over_the_twelve_month_mean() -> None:
    trend = REVENUE_RULE.apply(months((2025, 1), [100.0] * 9 + [200.0, 200.0, 200.0]))

    assert trend.months[-1].acceleration == 200.0 / 125.0
    assert [month.acceleration for month in trend.months[:-1]] == [None] * 11
    assert trend.accelerating_months == 1


def test_the_months_in_a_row_that_accelerated_count_back_from_the_latest() -> None:
    trend = REVENUE_RULE.apply(months((2025, 1), [100.0] * 12 + [90.0, 120.0, 130.0, 140.0]))

    assert [month.acceleration is not None and month.acceleration > 1 for month in trend.months[-4:]] == [False, True, True, True]
    assert trend.accelerating_months == 3


def test_revenue_under_its_longer_average_counts_as_months_of_slowing() -> None:
    trend = REVENUE_RULE.apply(months((2025, 1), [100.0] * 12 + [80.0, 70.0]))

    assert trend.accelerating_months == -2


def test_two_held_months_have_no_acceleration_and_draw_no_trend() -> None:
    trend = REVENUE_RULE.apply(months((2026, 9), [500.0, 600.0]))

    assert [month.acceleration for month in trend.months] == [None, None]
    assert trend.accelerating_months is None


def test_a_missing_month_inside_the_window_leaves_the_acceleration_unknown() -> None:
    held = months((2025, 1), [100.0] * 12)
    del held[5]

    assert REVENUE_RULE.apply(held).months[-1].acceleration is None


def test_a_blank_revenue_inside_the_window_leaves_the_acceleration_unknown() -> None:
    assert REVENUE_RULE.apply(months((2025, 1), [100.0] * 6 + [None] + [100.0] * 5)).months[-1].acceleration is None


def test_the_change_from_a_year_before_is_the_served_one_else_computed_from_the_month_held_a_year_before() -> None:
    served = REVENUE_RULE.apply([revenue(2026, 10, 150.0, year_over_year=59.71)])
    computed = REVENUE_RULE.apply(months((2025, 10), [100.0] + [100.0] * 11 + [125.0]))
    unknown = REVENUE_RULE.apply([revenue(2026, 10, 150.0)])

    assert served.months[-1].year_over_year == 0.5971
    assert computed.months[-1].year_over_year == 0.25
    assert (unknown.months[-1].year_over_year, unknown.growing_months) == (None, None)


def test_months_above_a_year_before_count_back_from_the_latest_and_below_count_negative() -> None:
    growing = REVENUE_RULE.apply([revenue(2026, 8, 1.0, -3.0), revenue(2026, 9, 1.0, 5.0), revenue(2026, 10, 1.0, 9.0)])
    shrinking = REVENUE_RULE.apply([revenue(2026, 9, 1.0, 5.0), revenue(2026, 10, 1.0, -9.0)])

    assert (growing.growing_months, shrinking.growing_months) == (2, -1)


def test_a_quarters_own_eps_is_the_year_to_date_less_the_quarter_before_and_unknown_without_it() -> None:
    trend = EarningsTrendRule().apply("2330", [], [page(2025, 2, 10.0), page(2025, 3, 17.0), page(2026, 1, 6.0), page(2026, 3, 30.0)])
    by_quarter = {str(result.quarter): result for result in trend.quarters}

    assert by_quarter["2025Q3"].quarter_eps == 7.0
    assert by_quarter["2025Q2"].quarter_eps is None
    assert by_quarter["2026Q1"].quarter_eps == 6.0
    assert by_quarter["2026Q3"].quarter_eps is None


def test_the_eps_change_compares_the_year_to_date_with_the_same_quarter_a_year_before() -> None:
    trend = EarningsTrendRule().apply("2330", [], [page(2025, 2, 10.0), page(2025, 3, 16.0), page(2026, 2, 12.0), page(2026, 3, 20.0)])

    assert [result.eps_year_over_year for result in trend.quarters] == [None, None, pytest.approx(0.2), 0.25]
    assert trend.eps_growing_quarters == 2
    assert trend.filed_eps_fetched_at == FETCHED


def test_a_loss_a_year_before_gives_no_eps_change() -> None:
    trend = EarningsTrendRule().apply("2330", [], [page(2025, 3, -1.0), page(2026, 3, 2.0)])

    assert trend.quarters[-1].eps_year_over_year is None
    assert trend.eps_growing_quarters is None


def test_the_archives_eps_wins_over_a_mops_page_of_the_same_quarter_and_other_companies_pages_are_ignored() -> None:
    archived = QuarterFinancials(quarter=FiscalQuarter(2026, 3), eps=5.47)
    trend = EarningsTrendRule().apply("1215", [archived], [page(2026, 3, 9.99, "1215"), page(2026, 2, 3.0, "9999")])

    assert [(str(result.quarter), result.eps_year_to_date) for result in trend.quarters] == [("2026Q3", 5.47)]
    assert trend.filed_eps_fetched_at is None


def test_margins_and_the_debt_ratio_come_from_the_statements_and_are_unknown_where_the_format_reports_none() -> None:
    industrial = QuarterFinancials(
        quarter=FiscalQuarter(2026, 3),
        revenue=1000.0,
        gross_profit=400.0,
        operating_income=250.0,
        net_income=200.0,
        total_assets=5000.0,
        total_liabilities=2000.0,
    )
    bank = QuarterFinancials(quarter=FiscalQuarter(2026, 3), revenue=1000.0, net_income=300.0)
    [made], [lent] = (EarningsTrendRule().apply("x", [quarter], []).quarters for quarter in (industrial, bank))

    assert (made.gross_margin, made.operating_margin, made.net_margin, made.debt_ratio) == (0.4, 0.25, 0.2, 0.4)
    assert (lent.gross_margin, lent.operating_margin, lent.net_margin, lent.debt_ratio) == (None, None, 0.3, None)


def test_a_ratios_median_is_given_only_once_enough_sessions_hold_it() -> None:
    day = date(2026, 11, 2)
    history = [ratios(day + timedelta(days=offset), pe) for offset, pe in enumerate([10.0, 30.0, 20.0, 25.0])]
    enough = ValuationStandingRule(min_sessions=4).apply(history)
    short = ValuationStandingRule(min_sessions=5).apply(history)

    assert (enough.pe_ratio.latest, enough.pe_ratio.median, enough.pe_ratio.sessions) == (25.0, 22.5, 4)
    assert (short.pe_ratio.latest, short.pe_ratio.median, short.pe_ratio.sessions) == (25.0, None, 4)
    assert (short.session_date, short.first_session, short.sessions) == (day + timedelta(days=3), day, 4)


def test_sessions_without_a_pe_do_not_count_toward_its_median() -> None:
    day = date(2026, 11, 2)
    standing = ValuationStandingRule(min_sessions=2).apply([ratios(day, None), ratios(day + timedelta(days=1), 12.0)])

    assert (standing.pe_ratio.sessions, standing.pe_ratio.median) == (1, None)
    assert (standing.pb_ratio.sessions, standing.pb_ratio.median) == (2, 2.0)


def test_the_reading_says_what_accelerated_grew_and_stands_above_its_median() -> None:
    day = date(2026, 11, 2)
    analysis = analysis_rule().apply(
        "2330",
        [],
        [replace_change(month, 12.0) for month in months((2025, 1), [100.0] * 12 + [90.0, 120.0, 130.0, 140.0])],
        [page(2025, 2, 10.0), page(2025, 3, 16.0), page(2026, 2, 12.0), page(2026, 3, 20.0)],
        [ratios(day + timedelta(days=offset), pe) for offset, pe in enumerate([10.0, 20.0, 30.0])],
    )

    assert analysis.readings == [
        Reading(ReadingKind.REVENUE_ACCELERATING, 3),
        Reading(ReadingKind.REVENUE_GROWING, 16),
        Reading(ReadingKind.EPS_UP, 2),
        Reading(ReadingKind.PE_ABOVE_MEDIAN, 3),
    ]


def replace_change(month: MonthlyRevenue, percent: float) -> MonthlyRevenue:
    return revenue(month.year, month.month, month.revenue, percent)


def test_the_reading_says_how_little_is_held_instead_of_drawing_a_trend() -> None:
    day = date(2026, 11, 12)
    analysis = analysis_rule(min_sessions=60).apply(
        "2330",
        [],
        months((2026, 9), [500.0, 600.0]),
        [page(2025, 4, 40.0), page(2026, 2, 25.0)],
        [ratios(day, 24.75), ratios(day + timedelta(days=1), 27.12)],
    )

    assert analysis.readings == [
        Reading(ReadingKind.REVENUE_HISTORY_SHORT, 2),
        Reading(ReadingKind.EPS_HISTORY_SHORT, 2),
        Reading(ReadingKind.VALUATION_HISTORY_SHORT, 2),
    ]


def test_a_stock_nothing_is_held_of_reads_as_no_data_and_a_loss_maker_as_no_pe() -> None:
    nothing = analysis_rule().apply("9103", [], [], [], [])
    loss = analysis_rule().apply("9103", [], [], [], [ratios(date(2026, 11, 12), None)])

    assert nothing.readings == [Reading(ReadingKind.NO_REVENUE), Reading(ReadingKind.NO_EPS), Reading(ReadingKind.NO_VALUATION)]
    assert loss.readings[-1] == Reading(ReadingKind.NO_PE)
