"""Menus 5 and 6 through the real CLI dispatch and ValuationPipeline, with only the ports faked (tests/support)."""

import io
from datetime import date, datetime

import pytest
from rich.console import Console
from support.harness import CliHarness, build_harness, falling_history, rising_history

from a_domain.model.fundamentals.eps import Eps, EpsUnavailable, EpsUnavailableReason, FiscalQuarter
from a_domain.model.valuation.scan import EliminationReason, ScanCriteria
from a_domain.model.valuation.valuation import LABEL, NOT_INVESTMENT_ADVICE, PeNotApplicable, PeNotApplicableReason, PeRatio, TargetPe
from a_domain.rules.ai.prompt import LOW_PE_RULE
from a_domain.types.enums import WatchlistType
from c_infrastructure.system.market_clock import TAIWAN_TIMEZONE
from d_presentation.cli import interactive

Q = FiscalQuarter
AFTER_CLOSE_FRIDAY = datetime(2026, 10, 30, 19, 0, tzinfo=TAIWAN_TIMEZONE)
THURSDAY = date(2026, 10, 29)

# Cumulative basic EPS as filed on MOPS (ajax_t163sb04, saved 2026-10-30).
FILINGS = {
    "2330": {Q(2026, 2): 49.33, Q(2025, 4): 66.26, Q(2025, 3): 46.75, Q(2025, 2): 29.31},
    "1101": {Q(2026, 2): 0.38, Q(2025, 4): -1.60, Q(2025, 3): -1.28, Q(2025, 2): 0.07},
    "1232": {Q(2026, 3): 8.03, Q(2026, 2): 4.71, Q(2025, 4): 8.25, Q(2025, 3): 5.84, Q(2025, 2): 3.93},
    "2603": {Q(2026, 2): 11.24, Q(2025, 4): 31.68, Q(2025, 3): 27.74, Q(2025, 2): 17.70},
}
CLOSES = {"2330": 2415.0, "1101": 28.2, "1232": 150.0, "2603": 60.0, "0050": 107.25}
INDUSTRIES = {"2330": "半導體業", "1101": "水泥工業", "1232": "食品工業", "2603": "航運業"}


def market_harness(now: datetime = AFTER_CLOSE_FRIDAY, market_open: bool = False) -> CliHarness:
    """2330 trends up, 2603 trends down, 1232 has no daily history, 1101 lost money, 0050 files no EPS."""
    harness = build_harness(now=now, market_open=market_open)
    history = {"2330": rising_history(2415.0), "2603": falling_history(60.0), "1232": [], "1101": rising_history(28.2)}

    for stock_id, price in CLOSES.items():
        harness.list_stock(stock_id, history.get(stock_id, []))
        harness.publish_close(stock_id, price, THURSDAY)

    for stock_id, filings in FILINGS.items():
        harness.file_eps(stock_id, filings, INDUSTRIES[stock_id])

    return harness


def capture_cli_output(monkeypatch: pytest.MonkeyPatch) -> io.StringIO:
    output = io.StringIO()
    monkeypatch.setattr(interactive, "console", Console(file=output, width=400))
    return output


@pytest.mark.asyncio
async def test_market_load_values_every_stock_from_filings_and_official_closes() -> None:
    harness = market_harness()

    market = await harness.valuation.load_market()

    assert harness.fundamentals.requested == [{Q(2026, 3), Q(2026, 2), Q(2025, 4), Q(2025, 3), Q(2025, 2)}]
    tsmc = market.find("2330")
    assert tsmc is not None
    assert isinstance(tsmc.eps, Eps)
    assert tsmc.eps.value == round(49.33 + 66.26 - 29.31, 2)
    assert tsmc.current_pe == PeRatio(price=2415.0, eps=86.28)
    assert tsmc.stock.industry == "半導體業"
    assert tsmc.close_is_fresh
    assert market.find("1101").current_pe == PeNotApplicable(PeNotApplicableReason.EPS_NEGATIVE)
    assert market.find("0050").current_pe == PeNotApplicable(PeNotApplicableReason.EPS_UNAVAILABLE)
    assert market.last_closed_session == date(2026, 10, 30)
    assert harness.stocks.stocks["2330"].eps == EpsUnavailable(EpsUnavailableReason.NOT_LOADED)


@pytest.mark.asyncio
async def test_failed_quarter_is_reported_and_never_turns_into_zero() -> None:
    harness = market_harness()
    harness.fundamentals.failed_quarters.add(Q(2025, 4))

    market = await harness.valuation.load_market()

    assert market.find("2330").eps == EpsUnavailable(EpsUnavailableReason.SOURCE_FAILED, Q(2025, 4))
    assert any("2025Q4" in warning for warning in market.source_warnings)


@pytest.mark.asyncio
async def test_numbers_come_from_the_domain_and_never_from_the_ai() -> None:
    harness = market_harness()
    harness.ai.valuation_replies["2330"] = {
        "higher_pe_factors": ["先進製程需求強勁"],
        "pe_derating_risks": ["客戶庫存調整"],
        "data_gaps": [],
        "summary": "依指定本益比，股價略高於基準合理價。",
        "fair_price": 9999,
        "eps": 123.45,
    }
    market = await harness.valuation.load_market()

    explanation = await harness.valuation.explain(market.appraise(market.find("2330"), TargetPe(25)))

    prompt = harness.ai.calls[0].prompt
    assert "27.99 倍" in prompt
    assert "基準 2,157.00 元" in prompt
    assert harness.news.requested == ["2330"]
    printed = "\n".join(line for section in explanation.sections() for line in section.lines)
    assert "先進製程需求強勁" in printed
    assert "客戶庫存調整" in printed
    assert "9999" not in printed
    assert "123.45" not in printed
    assert NOT_INVESTMENT_ADVICE in printed


@pytest.mark.asyncio
async def test_loss_making_stock_never_asks_the_ai_for_a_fair_price() -> None:
    harness = market_harness()
    market = await harness.valuation.load_market()

    await harness.valuation.explain(market.appraise(market.find("1101"), TargetPe(25)))

    prompt = harness.ai.calls[0].prompt
    assert "No fair price was computed because: 虧損，本益比不適用" in prompt
    assert "不適用：虧損，本益比不適用" in prompt
    assert "基準 " not in prompt


@pytest.mark.asyncio
async def test_failed_ai_call_still_yields_every_report_item() -> None:
    harness = market_harness()
    harness.ai.failures["2330"] = TimeoutError("AI provider timed out")
    market = await harness.valuation.load_market()

    explanation = await harness.valuation.explain(market.appraise(market.find("2330"), TargetPe(25)))

    sections = {section.title: section.lines for section in explanation.sections()}
    assert len(sections) == 11
    assert any("AI 解釋無法取得" in line for line in sections["資料不足警告"])


@pytest.mark.asyncio
async def test_scan_then_technical_step_records_where_each_stock_left() -> None:
    harness = market_harness()
    market = await harness.valuation.load_market()

    strict = market.screen(ScanCriteria(target_pe=TargetPe(20), min_undervaluation=0.0))
    assert [report.stock.stock_id for report in strict.survivors] == ["2603", "1232"]
    assert {elimination.report.stock.stock_id: elimination.reason for elimination in strict.eliminations} == {
        "2330": EliminationReason.BELOW_MIN_UNDERVALUATION,
        "1101": EliminationReason.EPS_NOT_POSITIVE,
        "0050": EliminationReason.EPS_UNAVAILABLE,
    }

    confirmed = await harness.valuation.confirm_technical(market.screen(ScanCriteria(target_pe=TargetPe(30), min_undervaluation=0.0)))

    assert [report.stock.stock_id for report in confirmed.survivors] == ["2330"]
    assert confirmed.technical_strategy_id == "trend"
    assert confirmed.technical_eliminations["2603"].reason == EliminationReason.TECHNICAL_HARD_FAILURE
    assert confirmed.technical_eliminations["1232"].reason == EliminationReason.NO_PRICE_HISTORY
    assert harness.ai.calls == []


@pytest.mark.asyncio
async def test_undervalued_stock_prompt_asks_the_ai_to_explain_low_pe_causes() -> None:
    harness = market_harness()
    market = await harness.valuation.load_market()
    scan = market.screen(ScanCriteria(target_pe=TargetPe(20), min_undervaluation=0.0))

    await harness.valuation.explain(scan.survivors[0])

    assert LOW_PE_RULE in harness.ai.calls[0].prompt


@pytest.mark.asyncio
async def test_menu_5_reports_each_stock_and_rejects_invalid_targets(monkeypatch: pytest.MonkeyPatch) -> None:
    harness = market_harness()
    output = capture_cli_output(monkeypatch)

    asked = await harness.run_valuation_menu("5", answers=["2330 1101 0050 9999", "abc", "0", "inf", "25"])

    printed = output.getvalue()
    assert [question.split(" (")[0] for question in asked] == ["Enter stock IDs separated by space or comma"] + ["Target P/E"] * 4
    assert printed.count("目標本益比必須是大於 0 的有限數字") == 3
    assert "Stock not found: 9999" in printed
    assert [call.stock_id for call in harness.ai.calls] == ["2330", "1101", "0050"]
    assert printed.count(LABEL) >= 3
    assert "86.28 元（近四季 TTM，2025Q3–2026Q2，實際值，公開資訊觀測站" in printed
    assert "2,415.00 元（2026-10-29 收盤，交易所公告）" in printed
    assert "虧損，本益比不適用" in printed
    assert "資料不足" in printed
    assert printed.count(NOT_INVESTMENT_ADVICE) == 3


@pytest.mark.asyncio
async def test_menu_5_blank_target_cancels_before_any_ai_call(monkeypatch: pytest.MonkeyPatch) -> None:
    harness = market_harness()
    output = capture_cli_output(monkeypatch)

    await harness.run_valuation_menu("5", answers=["2330", ""])

    assert harness.ai.calls == []
    assert "Target P/E cancelled" in output.getvalue()


@pytest.mark.asyncio
async def test_menu_6_scans_confirms_technically_and_explains_the_survivor(monkeypatch: pytest.MonkeyPatch) -> None:
    harness = market_harness()
    output = capture_cli_output(monkeypatch)

    await harness.run_valuation_menu("6", answers=["30", "0"], confirm=[True, True])

    printed = output.getvalue()
    assert "Market median P/E for reference" in printed
    assert "Scanned 5 -> passed 3" in printed
    assert "Eliminated at valuation: EPS ≤ 0 1 | EPS 資料不足 1" in printed
    assert "Two-step screen: valuation -> technical (trend)" in printed
    assert "Passed both steps: 1" in printed
    assert [call.stock_id for call in harness.ai.calls] == ["2330"]


@pytest.mark.asyncio
async def test_valuation_menus_never_place_orders_or_write_the_watchlist(monkeypatch: pytest.MonkeyPatch) -> None:
    harness = market_harness(now=datetime(2026, 10, 30, 10, 0, tzinfo=TAIWAN_TIMEZONE), market_open=True)
    capture_cli_output(monkeypatch)
    harness.list_stock("2330", rising_history(2415.0), realtime_price=2415.0)
    harness.publish_close("2330", 2415.0, THURSDAY)
    harness.hold("2330", quantity=1000, average_cost=2000.0)
    harness.watch("2330", WatchlistType.TECHNICAL)

    await harness.run_valuation_menu("5", answers=["2330 1232 2603", "100"])
    await harness.run_valuation_menu("6", answers=["100", "0"], confirm=[True, True])

    assert harness.broker.placed == []
    assert harness.signals.saved == []
    assert harness.watchlist.rows == [("2330", WatchlistType.TECHNICAL)]

    await harness.run_menu("4", stock_ids="2330", buy=["2330"])

    assert [order.stock_id for order in harness.broker.placed] == ["2330"]
