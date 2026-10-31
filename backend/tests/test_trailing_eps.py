from datetime import date, datetime

import pytest

from a_domain.model.fundamentals.eps import Eps
from a_domain.model.fundamentals.eps_unavailable import EpsUnavailable
from a_domain.model.fundamentals.fiscal_quarter import FiscalQuarter
from a_domain.model.fundamentals.quarter_eps import QuarterEps
from a_domain.model.market.stock import Stock
from a_domain.rules.collect.freshness import DailyCloseFreshnessRule, MissedSessionsRule
from a_domain.rules.fundamentals.filing_warning import FilingWarningRule
from a_domain.rules.fundamentals.trailing_eps import TrailingEpsRule
from a_domain.rules.fundamentals.trailing_eps_quarters import TrailingEpsQuartersRule
from a_domain.types.enums import EpsKind, EpsUnavailableReason

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

RULE = TrailingEpsRule()
TODAY = date(2026, 10, 30)


def filings(**overrides: dict[str, float] | None) -> dict[FiscalQuarter, QuarterEps | None]:
    result: dict[FiscalQuarter, QuarterEps | None] = {}

    for quarter, values in MOPS_CUMULATIVE_EPS.items():
        values = overrides.get(f"q{quarter.year}_{quarter.quarter}", values)
        result[quarter] = None if values is None else QuarterEps(quarter=quarter, cumulative_eps=values, fetched_at=FETCHED_AT)

    return result


def test_window_on_2026_10_30_is_the_quarter_being_filed_and_the_one_before() -> None:
    assert FiscalQuarter.filing_candidates(TODAY) == (Q(2026, 3), Q(2026, 2))
    assert TrailingEpsQuartersRule().apply(TODAY) == {Q(2026, 3), Q(2026, 2), Q(2025, 4), Q(2025, 3), Q(2025, 2)}


def test_window_in_january_uses_the_annual_report_being_filed() -> None:
    january = date(2027, 1, 15)

    assert FiscalQuarter.filing_candidates(january) == (Q(2026, 4), Q(2026, 3))
    assert TrailingEpsQuartersRule().apply(january) == {Q(2026, 4), Q(2026, 3), Q(2025, 4), Q(2025, 3)}


def test_ttm_for_a_q2_filer_adds_last_annual_and_removes_last_year_h1() -> None:
    eps = RULE.apply("2330", filings(), TODAY)

    assert isinstance(eps, Eps)
    assert eps.value == pytest.approx(49.33 + 66.26 - 29.31)
    assert eps.value == 86.28
    assert eps.kind == EpsKind.TRAILING_TWELVE_MONTHS
    assert (eps.period_start, eps.period_end) == (Q(2025, 3), Q(2026, 2))
    assert eps.newer_quarters == (Q(2026, 3),)


def test_ttm_uses_the_newest_quarter_the_company_has_filed() -> None:
    eps = RULE.apply("1232", filings(), TODAY)

    assert isinstance(eps, Eps)
    assert eps.value == round(8.03 + 8.25 - 5.84, 2)
    assert eps.period_end == Q(2026, 3)
    assert eps.newer_quarters == ()


def test_loss_making_ttm_stays_negative() -> None:
    eps = RULE.apply("1101", filings(), TODAY)

    assert isinstance(eps, Eps)
    assert eps.value == round(0.38 - 1.60 - 0.07, 2) == -1.29


def test_ttm_ending_in_q4_is_the_annual_report() -> None:
    annual = {
        Q(2025, 4): QuarterEps(quarter=Q(2025, 4), cumulative_eps={"2330": 66.26}, fetched_at=FETCHED_AT),
        Q(2025, 3): QuarterEps(quarter=Q(2025, 3), cumulative_eps={}, fetched_at=FETCHED_AT),
        Q(2024, 4): QuarterEps(quarter=Q(2024, 4), cumulative_eps={}, fetched_at=FETCHED_AT),
        Q(2024, 3): QuarterEps(quarter=Q(2024, 3), cumulative_eps={}, fetched_at=FETCHED_AT),
    }

    eps = RULE.apply("2330", annual, date(2026, 2, 10))

    assert isinstance(eps, Eps)
    assert eps.value == 66.26
    assert (eps.period_start, eps.period_end) == (Q(2025, 1), Q(2025, 4))


def test_ttm_that_nets_to_zero_is_exactly_zero() -> None:
    overrides = {"q2026_3": {"9999": 0.3}, "q2025_4": {"9999": 0.1}, "q2025_3": {"9999": 0.4}}

    eps = RULE.apply("9999", filings(**overrides), TODAY)

    assert isinstance(eps, Eps)
    assert eps.value == 0


def test_stock_without_any_filing_is_unavailable_not_zero() -> None:
    assert RULE.apply("0050", filings(), TODAY) == EpsUnavailable(EpsUnavailableReason.NOT_REPORTED, Q(2026, 2))


def test_missing_prior_year_filing_is_incomplete_history() -> None:
    overrides = {"q2025_2": {"2330": 29.31}, "q2025_4": {"1101": -1.60}}

    assert RULE.apply("2330", filings(**overrides), TODAY) == EpsUnavailable(EpsUnavailableReason.INCOMPLETE_HISTORY, Q(2025, 4))


def test_failed_prior_year_fetch_is_source_failed() -> None:
    assert RULE.apply("2330", filings(q2025_2=None), TODAY) == EpsUnavailable(EpsUnavailableReason.SOURCE_FAILED, Q(2025, 2))


def test_failed_fetch_of_the_quarter_being_filed_falls_back_and_says_so() -> None:
    eps = RULE.apply("1232", filings(q2026_3=None), TODAY)

    assert isinstance(eps, Eps)
    assert eps.period_end == Q(2026, 2)
    assert eps.value == round(4.71 + 8.25 - 3.93, 2)
    assert eps.newer_quarters == (Q(2026, 3),)


def test_no_candidate_fetched_is_source_failed() -> None:
    result = RULE.apply("2330", filings(q2026_3=None, q2026_2=None), TODAY)

    assert result == EpsUnavailable(EpsUnavailableReason.SOURCE_FAILED, Q(2026, 2))


def test_eps_text_always_carries_its_period_kind_basis_and_source() -> None:
    eps = RULE.apply("2330", filings(), TODAY)

    assert isinstance(eps, Eps)
    assert eps.describe() == "86.28 TWD (TTM, 2025Q3–2026Q2, actual, MOPS, fetched 2026-10-30 18:06)"


def test_a_warning_names_each_failed_or_stale_quarter_oldest_first() -> None:
    stale = QuarterEps(quarter=Q(2026, 3), cumulative_eps={"1232": 8.03}, fetched_at=FETCHED_AT, refresh_failed=True)
    warnings = FilingWarningRule().apply({**filings(q2025_4=None), Q(2026, 3): stale})

    assert len(warnings) == 2
    assert warnings[0].startswith("MOPS 2025Q4 ")
    assert warnings[1].startswith("MOPS 2026Q3 ")
    assert "2026-10-30 18:06" in warnings[1]
    assert FilingWarningRule().apply(filings()) == ()


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
    assert DailyCloseFreshnessRule(max_missed_sessions=1).apply(session, last_closed_session) is fresh


def test_the_missed_session_limit_is_the_rule_setting() -> None:
    assert DailyCloseFreshnessRule(max_missed_sessions=2).apply(date(2026, 10, 29), date(2026, 11, 2))
    assert not DailyCloseFreshnessRule(max_missed_sessions=0).apply(date(2026, 10, 29), date(2026, 10, 30))


@pytest.mark.parametrize(
    ("session", "last_closed_session", "missed"),
    [
        (date(2026, 10, 30), date(2026, 10, 30), 0),
        (date(2026, 10, 29), date(2026, 10, 30), 1),
        (date(2026, 10, 30), date(2026, 11, 2), 1),
        (date(2026, 10, 28), date(2026, 11, 2), 3),
    ],
)
def test_missed_sessions_count_weekdays_after_the_session(session: date, last_closed_session: date, missed: int) -> None:
    assert MissedSessionsRule().apply(session, last_closed_session) == missed
