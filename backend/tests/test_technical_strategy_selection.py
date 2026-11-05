"""
Which technical strategy a run uses, seen through the harness: the CLI session's built-in strategy, else the owner's
saved Buzz or active strategy, and how much daily history the run fetches for it.
"""

import io
from datetime import datetime
from unittest.mock import patch

import pytest
from pydantic import TypeAdapter
from rich.console import Console
from rich.prompt import Confirm, Prompt
from support.formulas import LATEST_PRICE, compare, indicator, market, rule
from support.harness import CliHarness, build_harness, falling_history, harness_config, harness_settings, rising_history

from a_domain.model.market.stock import Stock
from a_domain.rules.technical.strategy import TechnicalSettings, TechnicalStrategy
from a_domain.types.enums import TradeAction, WatchlistType
from a_domain.types.errors import TechnicalSettingsConflictError
from b_application.config.trading_config import TechnicalConfig
from b_application.schemas.pipeline_status import PipelineStatus
from d_presentation.cli import interactive, terminal

pytestmark = pytest.mark.asyncio

STRATEGY = TypeAdapter(TechnicalStrategy)
OWNER = harness_config().technical.owner_id


@pytest.fixture
def screen(monkeypatch: pytest.MonkeyPatch) -> io.StringIO:
    output = io.StringIO()
    monkeypatch.setattr(terminal, "console", Console(file=output, width=250))
    return output


def reported(status: PipelineStatus, stock_id: str) -> tuple[int, list[str]]:
    report = status.stocks[stock_id].technical_report
    assert report is not None
    return report.score, report.hard_failures


def history_windows(harness: CliHarness) -> list[int]:
    """The calendar days of each daily-history request the runs make, from the first to the last requested day."""
    windows: list[int] = []
    fetch_history = harness.prices.fetch_history

    async def recording(stocks: list[Stock], start_date: datetime, end_date: datetime):
        windows.append((end_date.date() - start_date.date()).days)
        return await fetch_history(stocks, start_date, end_date)

    harness.prices.fetch_history = recording
    return windows


# --------------------------------- Pipeline --------------------------------- #


def stopped_out_holding() -> CliHarness:
    """A held stock whose fresh quote is below its stop-loss price, so Intraday's first orders are its SELL."""
    harness = build_harness()
    harness.list_stock("2330", rising_history(100.0), realtime_price=100.0)
    harness.hold("2330", quantity=1000, average_cost=120.0)
    return harness


async def test_a_run_reads_its_strategy_again_when_a_save_interrupts_the_first_read() -> None:
    harness = stopped_out_holding()
    harness.technical_settings.interrupted_loads = 1

    await harness.runtime.pipeline.run_intraday()

    assert [(order.stock_id, order.action) for order in harness.broker.placed] == [("2330", TradeAction.SELL)]


async def test_a_run_whose_strategy_read_is_interrupted_twice_fails_before_any_order() -> None:
    harness = stopped_out_holding()
    harness.technical_settings.interrupted_loads = 2

    with pytest.raises(TechnicalSettingsConflictError):
        await harness.runtime.pipeline.run_intraday()

    assert harness.broker.placed == []


TREND_FAILS = (75, ["Price Above MA_5"])
"""The saved active strategy's verdict on a stock below its 5-day average: its one block rule fails, 90 - 15."""

BUZZ_PASSES = (90, [])
"""The saved Buzz strategy's verdict on the same stock, priced at 50: only a minimum price of 15."""


@pytest.mark.parametrize(
    ("menu", "verdict"),
    [("1", TREND_FAILS), ("2", BUZZ_PASSES), ("3", TREND_FAILS), ("4", TREND_FAILS)],
    ids=["full-cycle", "buzz", "intraday", "specific-stocks"],
)
async def test_buzz_runs_the_saved_buzz_strategy_and_every_other_workflow_the_saved_active_one(
    menu: str, verdict: tuple[int, list[str]]
) -> None:
    harness = build_harness()
    harness.list_stock("2603", falling_history(50.0), realtime_price=50.0)
    harness.discuss("2603", mentions=1, engagement=harness.config.collect_rules.buzz_min_engagement)
    harness.watch("2603", WatchlistType.TECHNICAL)

    status = await harness.run_menu(menu, stock_ids="2603")

    assert reported(status, "2603") == verdict


async def test_a_run_given_a_built_in_strategy_uses_it_and_leaves_the_saved_settings_alone() -> None:
    harness = build_harness()
    harness.list_stock("2330", rising_history(100.0), realtime_price=100.0)

    with_built_in = await harness.runtime.pipeline.analyse_specific_stocks(["2330"], built_in_strategy_id="aggressive")
    with_saved = await harness.runtime.pipeline.analyse_specific_stocks(["2330"])

    assert reported(with_built_in, "2330") == (0, ["Need 61 daily bars; received 10"])
    assert reported(with_saved, "2330") == (90, [])
    assert harness.technical_settings.saved == {OWNER: harness_settings()}


async def test_an_unknown_built_in_strategy_stops_the_run_before_it_starts() -> None:
    harness = build_harness()
    harness.list_stock("2330", rising_history(100.0))

    with pytest.raises(ValueError, match="my_balanced"):
        await harness.runtime.pipeline.run_full_cycle(built_in_strategy_id="my_balanced")

    assert (harness.journal.runs, harness.prices.history_requests) == ({}, [])


LONG_TREND = STRATEGY.validate_python(
    {
        "strategy_id": "long_trend",
        "name": "Long trend",
        "indicators": {"ind_a": {"kind": "sma", "period": 100}},
        "scoring": {},
        "rules": [rule("Close crosses above MA_100", compare(market("close"), "crosses_above", indicator("ind_a")))],
    }
)
"""Needs 101 daily bars: 100 for the average and one more for the bar before the crossing."""


@pytest.mark.parametrize(
    ("settings", "built_in_strategy_id", "days", "hard_failures"),
    [
        pytest.param(harness_settings(), None, 30, [], id="5-bar-strategy-gets-the-shortest-window"),
        pytest.param(
            TechnicalSettings(active_strategy_id="long_trend", buzz_strategy_id="long_trend", strategies=(LONG_TREND,)),
            None,
            152,
            ["Need 101 daily bars; received 10"],
            id="101-bar-strategy",
        ),
        pytest.param(harness_settings(), "balanced", 92, ["Need 61 daily bars; received 10"], id="61-bar-built-in-strategy"),
    ],
)
async def test_a_run_fetches_enough_calendar_days_for_the_bars_its_strategy_needs(
    settings: TechnicalSettings, built_in_strategy_id: str | None, days: int, hard_failures: list[str]
) -> None:
    """With lookback_days 30 and 1.5 calendar days per bar: max(30, 5 x 1.5), max(30, 101 x 1.5), max(30, 61 x 1.5)."""
    config = harness_config()
    config.analysis = config.analysis.model_copy(update={"lookback_days": 30, "history_calendar_days_per_bar": 1.5})
    harness = build_harness(config=config, settings=settings)
    harness.list_stock("2330", rising_history(100.0), realtime_price=100.0)
    windows = history_windows(harness)

    status = await harness.runtime.pipeline.analyse_specific_stocks(["2330"], built_in_strategy_id=built_in_strategy_id)

    assert windows == [days]
    assert reported(status, "2330")[1] == hard_failures, "the window is an estimate: a stock with fewer bars still fails"


# ---------------------------------- Menu 8 ---------------------------------- #


async def choose(
    harness: CliHarness, session: terminal.CliSession, menu: str, *answers: str | None
) -> tuple[PipelineStatus | None, list[list[str] | None]]:
    """
    Runs one menu option in the session, answering its prompts in order (None is Ctrl-C) and no to every yes/no
    question. Returns the option's status and the choices each prompt offered.
    """
    remaining = list(answers)
    offered: list[list[str] | None] = []

    def answer(question: str, *args, choices: list[str] | None = None, **kwargs) -> str:
        offered.append(choices)
        if (reply := remaining.pop(0)) is None:
            raise KeyboardInterrupt
        return reply

    with patch.object(Prompt, "ask", answer), patch.object(Confirm, "ask", lambda *args, **kwargs: False):
        status = await interactive.run_menu_option(menu, harness.runtime, session)

    assert remaining == [], "the option asked fewer questions than answered"
    return status, offered


async def test_menu_8_offers_exactly_the_three_built_in_strategies_and_cancel(screen: io.StringIO) -> None:
    harness = build_harness()

    _, offered = await choose(harness, terminal.CliSession(), "8", "0")

    listed = [line for line in screen.getvalue().splitlines() if line.startswith("[")]
    assert listed == ["[1] Conservative", "[2] Balanced", "[3] Aggressive", "[0] Cancel"]
    assert offered == [["0", "1", "2", "3"]]


def built_in(strategy_id: str, base_score: int) -> TechnicalStrategy:
    return STRATEGY.validate_python(
        {
            "strategy_id": strategy_id,
            "name": strategy_id.title(),
            "indicators": {},
            "scoring": {"base_score": base_score},
            "rules": [rule("Priced", compare(LATEST_PRICE, "gt", 0))],
        }
    )


def harness_with_built_ins() -> CliHarness:
    """Three built-in strategies that score every priced stock 70, 80 and 60, and saved settings that score it 90."""
    config = harness_config()
    config.technical = TechnicalConfig(
        owner_id=OWNER,
        built_in_strategies=(built_in("first", 70), built_in("second", 80), built_in("third", 60)),
        initial_strategy_id="first",
    )
    harness = build_harness(config=config)
    harness.list_stock("2330", rising_history(100.0), realtime_price=100.0)
    return harness


@pytest.mark.parametrize(("choice", "score"), [("1", 70), ("2", 80), ("3", 60)])
async def test_a_built_in_strategy_loaded_from_menu_8_scores_the_sessions_later_runs(choice: str, score: int) -> None:
    harness = harness_with_built_ins()
    session = terminal.CliSession()

    assert await choose(harness, session, "8", choice) == (None, [["0", "1", "2", "3"]])
    specific, _ = await choose(harness, session, "4", "2330")
    full_cycle, _ = await choose(harness, session, "1")

    assert reported(specific, "2330") == reported(full_cycle, "2330") == (score, [])
    assert harness.technical_settings.saved == {OWNER: harness_settings()}


@pytest.mark.parametrize("cancel", ["0", None], ids=["cancel", "ctrl-c"])
async def test_cancelling_menu_8_keeps_the_strategy_the_session_had(cancel: str | None) -> None:
    harness = harness_with_built_ins()
    session = terminal.CliSession()

    await choose(harness, session, "8", cancel)
    saved, _ = await choose(harness, session, "4", "2330")
    await choose(harness, session, "8", "2")
    await choose(harness, session, "8", cancel)
    second, _ = await choose(harness, session, "4", "2330")

    assert (reported(saved, "2330"), reported(second, "2330")) == ((90, []), (80, []))
    assert harness.technical_settings.saved == {OWNER: harness_settings()}


async def test_a_new_cli_session_starts_on_the_saved_settings() -> None:
    harness = harness_with_built_ins()
    await choose(harness, terminal.CliSession(), "8", "2")

    status, _ = await choose(harness, terminal.CliSession(), "4", "2330")

    assert reported(status, "2330") == (90, [])
