from datetime import date, datetime

import pytest

from a_domain.model.fundamentals.eps import Eps, EpsKind, EpsUnavailable, EpsUnavailableReason, FiscalQuarter, QuarterEps
from a_domain.model.market.stock import Stock
from a_domain.rules.collect.freshness import DailyCloseFreshnessRule
from a_domain.rules.fundamentals.trailing_eps import TrailingEpsRule

FETCHED_AT = datetime(2026, 10, 30, 18, 6)
Q = FiscalQuarter

# Cumulative basic EPS as published on MOPS ajax_t163sb04 (sii pages saved on 2026-10-30).
MOPS_CUMULATIVE_EPS = {
    Q(2026, 3): {"1232": 8.03},
    Q(2026, 2): {"2330": 49.33, "1101": 0.38, "1232": 4.71},
    Q(2025, 4): {"2330": 66.26, "1101": -1.60, "1232": 8.25},
    Q(2025, 3): {"2330": 46.75, "1101": -1.28, "1232": 5.84},
    Q(2025, 2): {"2330": 29.31, "1101": 0.07, "1232": 3.93},
}

RULE = TrailingEpsRule.as_of(date(2026, 10, 30))


def filings(**overrides: dict[str, float] | None) -> dict[FiscalQuarter, QuarterEps | None]:
    result: dict[FiscalQuarter, QuarterEps | None] = {}

    for quarter, values in MOPS_CUMULATIVE_EPS.items():
        values = overrides.get(f"q{quarter.year}_{quarter.quarter}", values)
        result[quarter] = None if values is None else QuarterEps(quarter=quarter, cumulative_eps=values, fetched_at=FETCHED_AT)

    return result


def test_window_on_2026_10_30_is_the_quarter_being_filed_and_the_one_before() -> None:
    assert RULE.candidates == (Q(2026, 3), Q(2026, 2))
    assert RULE.required_quarters == {Q(2026, 3), Q(2026, 2), Q(2025, 4), Q(2025, 3), Q(2025, 2)}


def test_window_in_january_uses_the_annual_report_being_filed() -> None:
    rule = TrailingEpsRule.as_of(date(2027, 1, 15))

    assert rule.candidates == (Q(2026, 4), Q(2026, 3))
    assert rule.required_quarters == {Q(2026, 4), Q(2026, 3), Q(2025, 4), Q(2025, 3)}


def test_ttm_for_a_q2_filer_adds_last_annual_and_removes_last_year_h1() -> None:
    eps = RULE.evaluate("2330", filings())

    assert isinstance(eps, Eps)
    assert eps.value == pytest.approx(49.33 + 66.26 - 29.31)
    assert eps.value == 86.28
    assert eps.kind == EpsKind.TRAILING_TWELVE_MONTHS
    assert (eps.period_start, eps.period_end) == (Q(2025, 3), Q(2026, 2))
    assert eps.newer_quarters == (Q(2026, 3),)


def test_ttm_uses_the_newest_quarter_the_company_has_filed() -> None:
    eps = RULE.evaluate("1232", filings())

    assert isinstance(eps, Eps)
    assert eps.value == round(8.03 + 8.25 - 5.84, 2)
    assert eps.period_end == Q(2026, 3)
    assert eps.newer_quarters == ()


def test_loss_making_ttm_stays_negative() -> None:
    eps = RULE.evaluate("1101", filings())

    assert isinstance(eps, Eps)
    assert eps.value == round(0.38 - 1.60 - 0.07, 2) == -1.29


def test_ttm_ending_in_q4_is_the_annual_report() -> None:
    rule = TrailingEpsRule.as_of(date(2026, 2, 10))
    annual = {
        Q(2025, 4): QuarterEps(quarter=Q(2025, 4), cumulative_eps={"2330": 66.26}, fetched_at=FETCHED_AT),
        Q(2025, 3): QuarterEps(quarter=Q(2025, 3), cumulative_eps={}, fetched_at=FETCHED_AT),
        Q(2024, 4): QuarterEps(quarter=Q(2024, 4), cumulative_eps={}, fetched_at=FETCHED_AT),
        Q(2024, 3): QuarterEps(quarter=Q(2024, 3), cumulative_eps={}, fetched_at=FETCHED_AT),
    }

    eps = rule.evaluate("2330", annual)

    assert isinstance(eps, Eps)
    assert eps.value == 66.26
    assert (eps.period_start, eps.period_end) == (Q(2025, 1), Q(2025, 4))


def test_ttm_that_nets_to_zero_is_exactly_zero() -> None:
    overrides = {"q2026_3": {"9999": 0.3}, "q2025_4": {"9999": 0.1}, "q2025_3": {"9999": 0.4}}

    eps = RULE.evaluate("9999", filings(**overrides))

    assert isinstance(eps, Eps)
    assert eps.value == 0


def test_stock_without_any_filing_is_unavailable_not_zero() -> None:
    assert RULE.evaluate("0050", filings()) == EpsUnavailable(EpsUnavailableReason.NOT_REPORTED, Q(2026, 2))


def test_missing_prior_year_filing_is_incomplete_history() -> None:
    overrides = {"q2025_2": {"2330": 29.31}, "q2025_4": {"1101": -1.60}}

    assert RULE.evaluate("2330", filings(**overrides)) == EpsUnavailable(EpsUnavailableReason.INCOMPLETE_HISTORY, Q(2025, 4))


def test_failed_prior_year_fetch_is_source_failed() -> None:
    assert RULE.evaluate("2330", filings(q2025_2=None)) == EpsUnavailable(EpsUnavailableReason.SOURCE_FAILED, Q(2025, 2))


def test_failed_fetch_of_the_quarter_being_filed_falls_back_and_says_so() -> None:
    eps = RULE.evaluate("1232", filings(q2026_3=None))

    assert isinstance(eps, Eps)
    assert eps.period_end == Q(2026, 2)
    assert eps.value == round(4.71 + 8.25 - 3.93, 2)
    assert eps.newer_quarters == (Q(2026, 3),)


def test_no_candidate_fetched_is_source_failed() -> None:
    result = RULE.evaluate("2330", filings(q2026_3=None, q2026_2=None))

    assert result == EpsUnavailable(EpsUnavailableReason.SOURCE_FAILED, Q(2026, 2))


def test_eps_text_always_carries_its_period_kind_basis_and_source() -> None:
    eps = RULE.evaluate("2330", filings())

    assert isinstance(eps, Eps)
    assert eps.describe() == "86.28 元（近四季 TTM，2025Q3–2026Q2，實際值，公開資訊觀測站，取得 2026-10-30 18:06）"


def test_quarter_is_final_a_week_after_the_latest_filing_deadline() -> None:
    assert not Q(2026, 3).is_final_on(date(2026, 12, 6))
    assert Q(2026, 3).is_final_on(date(2026, 12, 7))
    assert Q(2025, 4).filing_deadline == date(2026, 3, 31)


def test_stock_eps_defaults_to_unavailable_not_zero() -> None:
    stock = Stock(stock_id="2330")

    assert stock.eps == EpsUnavailable(EpsUnavailableReason.NOT_LOADED)
    assert stock.model_copy(deep=True).eps == stock.eps


@pytest.mark.parametrize(
    ("session", "last_closed_session", "fresh"),
    [
        (date(2026, 10, 30), date(2026, 10, 30), True),
        (date(2026, 10, 29), date(2026, 10, 30), True),
        (date(2026, 10, 30), date(2026, 11, 2), True),
        (date(2026, 10, 29), date(2026, 11, 2), False),
        (date(2026, 10, 28), date(2026, 10, 30), False),
    ],
)
def test_daily_close_is_stale_after_two_missed_weekday_sessions(session: date, last_closed_session: date, fresh: bool) -> None:
    assert DailyCloseFreshnessRule().is_fresh(session, last_closed_session) is fresh
