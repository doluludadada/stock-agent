import math
from datetime import date, datetime, time, timedelta, timezone

import pytest
from icontract import ViolationError

from a_domain.model.analysis.technical_report import TechnicalReport
from a_domain.model.fundamentals.eps import Eps
from a_domain.model.fundamentals.eps_unavailable import EpsUnavailable
from a_domain.model.fundamentals.fiscal_quarter import FiscalQuarter
from a_domain.model.market.ohlcv import Ohlcv
from a_domain.model.market.stock import Stock
from a_domain.model.valuation.fair_price_range import FairPriceRange
from a_domain.model.valuation.market_valuation import MarketValuation
from a_domain.model.valuation.pe_not_applicable import PeNotApplicable
from a_domain.model.valuation.pe_ratio import PeRatio
from a_domain.model.valuation.scan_criteria import ScanCriteria
from a_domain.model.valuation.stock_valuation import StockValuation
from a_domain.model.valuation.target_pe import TargetPe
from a_domain.model.valuation.valuation_explanation import LOW_PE_CAVEAT, NOT_INVESTMENT_ADVICE, ValuationExplanation
from a_domain.model.valuation.valuation_report import ValuationReport
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

TAIPEI = timezone(timedelta(hours=8))
LAST_CLOSED_SESSION = date(2026, 10, 30)
SPREAD = 0.2

US_107_SECTIONS = [
    "目前股價",
    "EPS 與財報期間",
    "目前本益比",
    "目標本益比",
    "推算合理股價（基於指定本益比的估值）",
    "高估／低估幅度",
    "可能支持較高本益比的因素",
    "可能導致本益比下修的風險",
    "資料不足警告",
    "非投資建議聲明",
    "AI 摘要",
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
    eps: float | EpsUnavailable,
    price: float | None,
    session: date = LAST_CLOSED_SESSION,
    industry: str | None = "半導體業",
) -> StockValuation:
    stock = Stock(stock_id=stock_id, name=f"Stock {stock_id}", industry=industry)
    stock.eps = eps if isinstance(eps, EpsUnavailable) else ttm(eps)
    close = None

    if price is not None:
        close = Ohlcv(ts=datetime.combine(session, time(13, 30), TAIPEI), open=price, high=price, low=price, close=price, volume=1)

    return StockValuation(stock=stock, close=close, last_closed_session=LAST_CLOSED_SESSION)


def market(*valuations: StockValuation) -> MarketValuation:
    return MarketValuation(
        valuations={item.stock.stock_id: item for item in valuations}, last_closed_session=LAST_CLOSED_SESSION, scenario_spread=SPREAD
    )


def test_current_pe_is_price_over_ttm_eps() -> None:
    pe = valuation("2330", 86.28, 2415.0).current_pe

    assert isinstance(pe, PeRatio)
    assert pe.value == pytest.approx(2415.0 / 86.28)
    assert valuation("2330", 86.28, 2415.0).pe_text == "27.99 倍"


@pytest.mark.parametrize(
    ("eps", "price", "reason", "label"),
    [
        (0.0, 50.0, PeNotApplicableReason.EPS_ZERO, "無法計算"),
        (-1.29, 28.2, PeNotApplicableReason.EPS_NEGATIVE, "虧損，本益比不適用"),
        (
            EpsUnavailable(EpsUnavailableReason.NOT_REPORTED, FiscalQuarter(2026, 2)),
            107.25,
            PeNotApplicableReason.EPS_UNAVAILABLE,
            "資料不足",
        ),
        (3.0, None, PeNotApplicableReason.INVALID_PRICE, "無有效股價"),
    ],
)
def test_current_pe_outcomes_are_a_closed_set(
    eps: float | EpsUnavailable, price: float | None, reason: PeNotApplicableReason, label: str
) -> None:
    item = valuation("9999", eps, price)

    assert item.current_pe == PeNotApplicable(reason)
    assert item.pe_text == label


def test_fair_price_scenarios_follow_eps_times_target_pe() -> None:
    report = ValuationReport.appraise(valuation("2330", 86.28, 2415.0), TargetPe(25), SPREAD)

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
    report = ValuationReport.appraise(valuation("2330", 86.28, 2415.0), TargetPe(25), SPREAD)
    sections = {section.title: section.lines for section in report.fact_sections()}

    assert sections["推算合理股價（基於指定本益比的估值）"] == (
        "保守 1,725.60 元｜本益比 20.00 倍｜假設：基準 × (1 − 20%)，依設定 valuation.scenario_spread",
        "基準 2,157.00 元｜本益比 25.00 倍｜假設：使用者輸入的目標本益比",
        "樂觀 2,588.40 元｜本益比 30.00 倍｜假設：基準 × (1 + 20%)，依設定 valuation.scenario_spread",
    )
    assert sections["高估／低估幅度"][1] == "基準 價差 -258.00 元，高估 10.7%"


@pytest.mark.parametrize("eps", [0.0, -1.29, EpsUnavailable(EpsUnavailableReason.SOURCE_FAILED, FiscalQuarter(2026, 3))])
def test_no_fair_price_when_eps_is_not_positive_or_missing(eps: float | EpsUnavailable) -> None:
    report = ValuationReport.appraise(valuation("1101", eps, 28.2), TargetPe(15), SPREAD)
    sections = {section.title: section.lines for section in report.fact_sections()}

    assert isinstance(report.fair_value, PeNotApplicable)
    assert report.undervaluation is None
    assert sections["推算合理股價（基於指定本益比的估值）"][0].startswith("不適用")
    assert sections["高估／低估幅度"] == ("不適用",)


def test_a_computable_pe_needs_a_target() -> None:
    with pytest.raises(ValueError):
        ValuationReport.appraise(valuation("2330", 86.28, 2415.0), None, SPREAD)


@pytest.mark.parametrize("value", [0.0, -5.0, math.nan, math.inf])
def test_target_pe_must_be_finite_and_positive(value: float) -> None:
    with pytest.raises(ValueError, match="目標本益比"):
        TargetPe(value)


@pytest.mark.parametrize("value", [-0.1, math.nan])
def test_minimum_undervaluation_must_be_finite_and_not_negative(value: float) -> None:
    with pytest.raises(ValueError):
        ScanCriteria(target_pe=TargetPe(12), min_undervaluation=value)


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
    scan = scan_market().screen(ScanCriteria(target_pe=TargetPe(12), min_undervaluation=0.2))

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
    scan = scan_market().screen(ScanCriteria(target_pe=TargetPe(12), min_undervaluation=0.0))
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

    with pytest.raises(ViolationError):
        confirmed.after_technical_step("moderate")


def test_technical_step_without_price_history_eliminates_at_the_technical_step() -> None:
    scan = scan_market().screen(ScanCriteria(target_pe=TargetPe(12), min_undervaluation=0.2))

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


def test_stale_close_is_valued_but_warned() -> None:
    item = valuation("7777", 4.0, 10.0, session=date(2026, 10, 28))

    assert isinstance(item.current_pe, PeRatio)
    assert not item.close_is_fresh
    assert any(warning.startswith("股價過期：收盤日 2026-10-28") for warning in item.warnings)


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
    [
        (86.28, TargetPe(25)),
        (-1.29, TargetPe(25)),
        (-1.29, None),
        (EpsUnavailable(EpsUnavailableReason.NOT_REPORTED, FiscalQuarter(2026, 2)), None),
    ],
)
def test_every_report_lists_all_us_107_items(eps: float | EpsUnavailable, target: TargetPe | None) -> None:
    report = ValuationReport.appraise(valuation("2330", eps, 2415.0), target, SPREAD)

    for item in (explanation(report), ValuationExplanation.without_ai(report, "AI 解釋無法取得")):
        sections = item.sections()

        assert [section.title for section in sections] == US_107_SECTIONS
        assert all(section.lines for section in sections)
        assert sections[9].lines == (NOT_INVESTMENT_ADVICE,)


def test_missing_eps_report_says_data_is_insufficient() -> None:
    eps = EpsUnavailable(EpsUnavailableReason.NOT_REPORTED, FiscalQuarter(2026, 2))
    sections = {
        s.title: s.lines
        for s in ValuationExplanation.without_ai(
            ValuationReport.appraise(valuation("0050", eps, 107.25), None, SPREAD), "x"
        ).sections()
    }

    assert sections["EPS 與財報期間"][0].startswith("資料不足")
    assert sections["目前本益比"] == ("資料不足",)
    assert sections["資料不足警告"][0].startswith("資料不足")


def test_undervalued_report_carries_the_low_pe_caveat() -> None:
    cheap = ValuationReport.appraise(valuation("1111", 5.0, 40.0), TargetPe(12), SPREAD)
    expensive = ValuationReport.appraise(valuation("2330", 86.28, 2415.0), TargetPe(25), SPREAD)

    assert LOW_PE_CAVEAT in dict((s.title, s.lines) for s in explanation(cheap).sections())["可能導致本益比下修的風險"]
    assert LOW_PE_CAVEAT not in dict((s.title, s.lines) for s in explanation(expensive).sections())["可能導致本益比下修的風險"]
