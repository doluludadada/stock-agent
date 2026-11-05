import math
from dataclasses import replace
from datetime import date, datetime, time, timedelta, timezone

import pytest
from pydantic import ValidationError
from support.settings import shipped_config

from a_domain.model.analysis.technical_report import TechnicalReport
from a_domain.model.fundamentals.eps import Eps, EpsUnavailable
from a_domain.model.market.ohlcv import Ohlcv
from a_domain.model.market.stock import Stock
from a_domain.model.valuation.scan import MarketValuation, ScanCriteria
from a_domain.model.valuation.valuation import FairPriceRange, PeRatio, StockValuation, ValuationExplanation, ValuationReport
from a_domain.rules.fundamentals.filing import FilingDeadlineRule
from a_domain.rules.valuation.scan import ValuationStepRule
from a_domain.rules.valuation.valuation import AppraisalRule, ExplanationSectionsRule, FactSectionsRule, StockValuationRule
from a_domain.types.enums import (
    EliminationReason,
    EpsBasis,
    EpsKind,
    EpsUnavailableReason,
    InformationSource,
    PeNotApplicableReason,
    ScanStep,
    ScenarioName,
)
from a_domain.types.values import FiscalQuarter

TAIPEI = timezone(timedelta(hours=8))
LAST_CLOSED_SESSION = date(2026, 10, 30)
SHIPPED = shipped_config()
TEXTS = SHIPPED.valuation

STOCK_VALUATION = StockValuationRule(
    max_missed_sessions=1, filing_deadline_rule=FilingDeadlineRule(SHIPPED.sources.mops.filing_deadlines)
)
APPRAISAL = AppraisalRule(scenario_spread=0.2)
FACT_SECTIONS = FactSectionsRule(undervaluation_formula=TEXTS.undervaluation_formula)
EXPLANATION_SECTIONS = ExplanationSectionsRule(
    fact_sections_rule=FACT_SECTIONS,
    low_pe_caveat=TEXTS.low_pe_caveat,
    ai_not_provided=TEXTS.ai_not_provided,
    not_investment_advice=TEXTS.not_investment_advice,
)
VALUATION_STEP = ValuationStepRule(appraisal_rule=APPRAISAL, max_explanations=3)

US_107_SECTIONS = [
    "Current price",
    "EPS and reporting period",
    "Current P/E",
    "Target P/E",
    "Fair price (Valuation based on a specified P/E)",
    "Overvaluation / undervaluation",
    "Factors that may support a higher P/E",
    "Risks that may lower the P/E",
    "Insufficient data warnings",
    "Not investment advice",
    "AI summary",
]


def ttm(value: float) -> Eps:
    return Eps(
        value=value,
        kind=EpsKind.TRAILING_TWELVE_MONTHS,
        period_end=FiscalQuarter(2026, 2),
        basis=EpsBasis.ACTUAL,
        source=InformationSource.TWSE_MOPS,
        fetched_at=datetime(2026, 10, 30, 18, 6),
    )


def valuation(
    stock_id: str,
    eps: float | Eps | EpsUnavailable,
    price: float | None,
    session: date = LAST_CLOSED_SESSION,
    industry: str | None = "半導體業",
) -> StockValuation:
    stock = Stock(stock_id=stock_id, name=f"Stock {stock_id}", industry=industry)
    stock.eps = eps if isinstance(eps, Eps | EpsUnavailable) else ttm(eps)
    close = None

    if price is not None:
        close = Ohlcv(ts=datetime.combine(session, time(13, 30), TAIPEI), open=price, high=price, low=price, close=price, volume=1)

    return STOCK_VALUATION.apply(stock, close, LAST_CLOSED_SESSION)


def market(*valuations: StockValuation) -> MarketValuation:
    return MarketValuation(valuations={item.stock.stock_id: item for item in valuations}, last_closed_session=LAST_CLOSED_SESSION)


def test_current_pe_is_price_over_ttm_eps() -> None:
    pe = valuation("2330", 86.28, 2415.0).current_pe

    assert isinstance(pe, PeRatio)
    assert pe.value == pytest.approx(2415.0 / 86.28)
    assert valuation("2330", 86.28, 2415.0).pe_text == "27.99x"


@pytest.mark.parametrize(
    ("eps", "price", "reason", "label"),
    [
        (0.0, 50.0, PeNotApplicableReason.EPS_ZERO, "cannot be computed"),
        (-1.29, 28.2, PeNotApplicableReason.EPS_NEGATIVE, "loss-making, P/E not applicable"),
        (
            EpsUnavailable(EpsUnavailableReason.NOT_REPORTED, FiscalQuarter(2026, 2)),
            107.25,
            PeNotApplicableReason.EPS_UNAVAILABLE,
            "insufficient data",
        ),
        (3.0, None, PeNotApplicableReason.INVALID_PRICE, "no valid price"),
    ],
)
def test_current_pe_outcomes_are_a_closed_set(
    eps: float | EpsUnavailable, price: float | None, reason: PeNotApplicableReason, label: str
) -> None:
    item = valuation("9999", eps, price)

    assert item.current_pe == reason
    assert item.pe_text == label


def test_fair_price_scenarios_follow_eps_times_target_pe() -> None:
    report = APPRAISAL.apply(valuation("2330", 86.28, 2415.0), 25)

    assert isinstance(report.fair_value, FairPriceRange)
    scenarios = list(report.fair_value)
    assert [scenario.name for scenario in scenarios] == [ScenarioName.CONSERVATIVE, ScenarioName.BASE, ScenarioName.OPTIMISTIC]
    assert [scenario.target_pe for scenario in scenarios] == pytest.approx([20.0, 25.0, 30.0])
    assert [scenario.fair_price for scenario in scenarios] == pytest.approx([86.28 * 20, 86.28 * 25, 86.28 * 30])
    assert report.fair_value.base.gap == pytest.approx(86.28 * 25 - 2415.0)
    assert report.undervaluation == pytest.approx((86.28 * 25 - 2415.0) / 2415.0)
    assert not report.appears_undervalued
    assert all(scenario.assumption for scenario in scenarios)


def test_report_text_shows_every_scenario_with_its_assumption() -> None:
    report = APPRAISAL.apply(valuation("2330", 86.28, 2415.0), 25)
    sections = {section.title: section.lines for section in FACT_SECTIONS.apply(report)}

    assert sections["Fair price (Valuation based on a specified P/E)"] == (
        "Conservative 1,725.60 TWD | P/E 20.00x | assumption: base × (1 − 20%), from the valuation.scenario_spread setting",
        "Base 2,157.00 TWD | P/E 25.00x | assumption: the target P/E the user entered",
        "Optimistic 2,588.40 TWD | P/E 30.00x | assumption: base × (1 + 20%), from the valuation.scenario_spread setting",
    )
    assert sections["Overvaluation / undervaluation"][1] == "Base gap -258.00 TWD, overvalued by 10.7%"


@pytest.mark.parametrize("eps", [0.0, -1.29, EpsUnavailable(EpsUnavailableReason.SOURCE_FAILED, FiscalQuarter(2026, 3))])
def test_no_fair_price_when_eps_is_not_positive_or_missing(eps: float | EpsUnavailable) -> None:
    report = APPRAISAL.apply(valuation("1101", eps, 28.2), 15)
    sections = {section.title: section.lines for section in FACT_SECTIONS.apply(report)}

    assert isinstance(report.fair_value, PeNotApplicableReason)
    assert report.undervaluation is None
    assert sections["Fair price (Valuation based on a specified P/E)"][0].startswith("Not applicable")
    assert sections["Overvaluation / undervaluation"] == ("Not applicable",)


def test_a_computable_pe_needs_a_target() -> None:
    with pytest.raises(ValueError):
        APPRAISAL.apply(valuation("2330", 86.28, 2415.0), None)


@pytest.mark.parametrize("value", [0.0, -5.0, math.nan, math.inf])
def test_target_pe_must_be_finite_and_positive(value: float) -> None:
    with pytest.raises(ValidationError):
        ScanCriteria(target_pe=value, min_undervaluation=0.0)


@pytest.mark.parametrize("value", [-0.1, math.nan])
def test_minimum_undervaluation_must_be_finite_and_not_negative(value: float) -> None:
    with pytest.raises(ValidationError):
        ScanCriteria(target_pe=12, min_undervaluation=value)


def scan_market() -> MarketValuation:
    return market(
        valuation("1111", 5.0, 40.0),
        valuation("2222", 2.0, 20.0, industry="水泥工業"),
        valuation("3333", 1.0, 30.0),
        valuation("4444", -1.0, 10.0),
        valuation("5555", EpsUnavailable(EpsUnavailableReason.NOT_REPORTED, FiscalQuarter(2026, 2)), 50.0),
        valuation("6666", 3.0, None),
        valuation("7777", 4.0, 10.0, session=date(2026, 10, 28)),
    )


def test_screen_keeps_undervalued_stocks_sorted_and_records_why_others_left() -> None:
    scan = VALUATION_STEP.apply(scan_market(), ScanCriteria(target_pe=12, min_undervaluation=0.2))

    assert [report.stock.stock_id for report in scan.survivors] == ["1111", "2222"]
    assert [report.undervaluation for report in scan.survivors] == pytest.approx([(5 * 12 - 40) / 40, (2 * 12 - 20) / 20])
    assert {elimination.report.stock.stock_id: elimination.reason for elimination in scan.eliminations} == {
        "3333": EliminationReason.BELOW_MIN_UNDERVALUATION,
        "4444": EliminationReason.EPS_NOT_POSITIVE,
        "5555": EliminationReason.EPS_UNAVAILABLE,
        "6666": EliminationReason.PRICE_MISSING,
        "7777": EliminationReason.PRICE_STALE,
    }
    assert all(elimination.reason.step == ScanStep.VALUATION for elimination in scan.eliminations)


def test_technical_step_eliminates_hard_failures_and_missing_history_only() -> None:
    scan = VALUATION_STEP.apply(scan_market(), ScanCriteria(target_pe=12, min_undervaluation=0.0))
    reports = {report.stock.stock_id: report for report in scan.survivors}
    assert set(reports) == {"1111", "2222"}

    reports["1111"].stock.technical_report = TechnicalReport(score=40, hard_failures=["Liquidity Check"])
    reports["2222"].stock.technical_report = TechnicalReport(score=70, soft_failures=["ADX"])

    confirmed = scan.after_technical_step("moderate")

    assert [report.stock.stock_id for report in confirmed.survivors] == ["2222"]
    assert confirmed.technical_strategy_id == "moderate"
    assert confirmed.technical_eliminations["1111"].reason == EliminationReason.TECHNICAL_HARD_FAILURE
    assert confirmed.technical_eliminations["1111"].detail == "Liquidity Check"
    assert [report.stock.stock_id for report in confirmed.valuation_survivors] == ["1111", "2222"]
    assert confirmed.elimination_counts(ScanStep.TECHNICAL) == {EliminationReason.TECHNICAL_HARD_FAILURE: 1}

    with pytest.raises(ValueError, match="The technical step runs once"):
        confirmed.after_technical_step("moderate")


def test_technical_step_without_price_history_eliminates_at_the_technical_step() -> None:
    scan = VALUATION_STEP.apply(scan_market(), ScanCriteria(target_pe=12, min_undervaluation=0.2))

    confirmed = scan.after_technical_step("moderate")

    assert confirmed.survivors == ()
    assert {reason.step for reason in confirmed.elimination_counts(ScanStep.TECHNICAL)} == {ScanStep.TECHNICAL}
    assert confirmed.elimination_counts(ScanStep.TECHNICAL)[EliminationReason.NO_PRICE_HISTORY] == 2


def test_median_pe_uses_fresh_computable_ratios_only() -> None:
    reference = scan_market()

    market_median = reference.median_pe()
    assert market_median is not None
    assert (market_median.value, market_median.sample_size) == (10.0, 3)

    industry_median = reference.median_pe("水泥工業")
    assert industry_median is not None
    assert (industry_median.value, industry_median.sample_size) == (10.0, 1)
    assert reference.median_pe("金融保險業") is None


def test_each_valuation_carries_its_industrys_median_once_the_market_is_loaded() -> None:
    reference = scan_market()

    medians = {
        stock_id: valuation.industry_median_pe and valuation.industry_median_pe.value
        for stock_id, valuation in reference.with_industry_medians().valuations.items()
    }

    for stock_id, valuation in reference.valuations.items():
        industry = valuation.stock.industry
        expected = reference.median_pe(industry) if industry else None
        assert medians[stock_id] == (expected and expected.value), stock_id
    assert any(value is not None for value in medians.values())


def test_stale_close_is_valued_but_warned() -> None:
    item = valuation("7777", 4.0, 10.0, session=date(2026, 10, 28))

    assert isinstance(item.current_pe, PeRatio)
    assert not item.close_is_fresh
    assert any(warning.startswith("Stale price: closed on 2026-10-28") for warning in item.warnings)


def test_a_quarter_the_eps_does_not_include_is_warned_with_its_filing_deadline() -> None:
    item = valuation("2330", replace(ttm(86.28), newer_quarters=(FiscalQuarter(2026, 3),)), 2415.0)

    assert item.warnings == (
        "2026Q3 filings are not included (filing deadline 2026-11-29; the company has not filed yet or the data could "
        "not be fetched), so this run uses the TTM EPS through 2026Q2",
    )


def explanation(report: ValuationReport) -> ValuationExplanation:
    return ValuationExplanation(
        report=report,
        higher_pe_factors=("先進製程訂單能見度高",),
        pe_derating_risks=("地緣政治風險",),
        data_gaps=(),
        summary="摘要",
        raw_response="{}",
    )


@pytest.mark.parametrize(
    ("eps", "target"),
    [(86.28, 25), (-1.29, 25), (-1.29, None), (EpsUnavailable(EpsUnavailableReason.NOT_REPORTED, FiscalQuarter(2026, 2)), None)],
)
def test_every_report_lists_all_us_107_items(eps: float | EpsUnavailable, target: float | None) -> None:
    report = APPRAISAL.apply(valuation("2330", eps, 2415.0), target)

    for item in (explanation(report), ValuationExplanation.without_ai(report, "AI explanation unavailable")):
        sections = EXPLANATION_SECTIONS.apply(item)

        assert [section.title for section in sections] == US_107_SECTIONS
        assert all(section.lines for section in sections)
        assert sections[9].lines == (TEXTS.not_investment_advice,)


def test_missing_eps_report_says_data_is_insufficient() -> None:
    eps = EpsUnavailable(EpsUnavailableReason.NOT_REPORTED, FiscalQuarter(2026, 2))
    report = APPRAISAL.apply(valuation("0050", eps, 107.25), None)
    sections = {s.title: s.lines for s in EXPLANATION_SECTIONS.apply(ValuationExplanation.without_ai(report, "x"))}

    assert sections["EPS and reporting period"][0].startswith("Insufficient data")
    assert sections["Current P/E"] == ("insufficient data",)
    assert sections["Insufficient data warnings"][0].startswith("Insufficient data")


def test_undervalued_report_carries_the_low_pe_caveat() -> None:
    cheap = APPRAISAL.apply(valuation("1111", 5.0, 40.0), 12)
    expensive = APPRAISAL.apply(valuation("2330", 86.28, 2415.0), 25)

    def risks(report: ValuationReport) -> tuple[str, ...]:
        return dict((s.title, s.lines) for s in EXPLANATION_SECTIONS.apply(explanation(report)))["Risks that may lower the P/E"]

    assert TEXTS.low_pe_caveat in risks(cheap)
    assert TEXTS.low_pe_caveat not in risks(expensive)
