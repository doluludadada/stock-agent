import io
from contextlib import nullcontext
from unittest.mock import patch

import pytest
from rich.console import Console
from rich.prompt import Confirm, Prompt
from support.harness import MARKET_CLOSED, build_harness, falling_history, rising_history

from a_domain.types.enums import OrderStatus
from d_presentation.cli import interactive, terminal

pytestmark = pytest.mark.asyncio


@pytest.fixture
def screen(monkeypatch) -> io.StringIO:
    output = io.StringIO()
    monkeypatch.setattr(terminal, "console", Console(file=output, width=250))
    return output


async def test_a_refused_manual_buy_shows_its_status_and_reason(screen: io.StringIO) -> None:
    harness = build_harness(now=MARKET_CLOSED)
    harness.list_stock("2330", rising_history(100.0), realtime_price=100.0)

    await harness.run_menu("4", stock_ids="2330", buy={"2330"})

    [order] = harness.journal.orders.values()
    assert (order.status, harness.broker.placed) == (OrderStatus.REJECTED, [])
    assert f"Manual BUY result: 2330 | REJECTED | Filled 0/{order.quantity}" in screen.getvalue()
    assert "Reason: MARKET_CLOSED: Mon 2026-10-19 14:00 falls in the market's closed phase" in screen.getvalue()


async def test_a_filled_manual_buy_shows_the_fill_and_its_fee(screen: io.StringIO) -> None:
    harness = build_harness()
    harness.list_stock("2317", falling_history(100.0), realtime_price=98.0)

    await harness.run_menu("4", stock_ids="2317", buy={"2317"})

    [order] = harness.broker.placed
    assert f"Manual BUY result: 2317 | FILLED | Filled {order.quantity}/{order.quantity} @ 98.00 | Fee=" in screen.getvalue()


async def test_account_history_shows_positions_and_never_places_an_order(screen: io.StringIO) -> None:
    harness = build_harness()
    harness.list_stock("2330", rising_history(110.0), realtime_price=112.0)
    harness.hold("2330", quantity=1000, average_cost=100.0)

    await harness.show_account_history(as_of="2026-10-19")

    output = screen.getvalue()
    assert harness.broker.placed == []
    assert "Account Now" in output and "2330" in output and "112.00" in output
    assert "No fills recorded yet, so there is no equity curve." in output
    assert "No fill recorded on or before 2026-10-19." in output


async def test_exit_from_the_menu_shuts_down_and_says_the_system_stopped(screen: io.StringIO, monkeypatch) -> None:
    harness = build_harness()
    monkeypatch.setattr(interactive, "open_runtime", lambda: nullcontext(harness.runtime))

    with patch.object(Prompt, "ask", lambda *args, **kwargs: "0"):
        await interactive.interactive_menu()

    output = screen.getvalue()
    assert output.index("Shutting down...") < output.index("System stopped.")


async def test_account_history_warns_about_each_position_whose_price_is_not_a_live_quote(screen: io.StringIO) -> None:
    harness = build_harness()
    harness.list_stock("2330", rising_history(110.0), realtime_price=112.0)
    harness.list_stock("2317", rising_history(50.0))
    harness.list_stock("2603", [])
    harness.hold("2330", quantity=1000, average_cost=100.0)
    harness.hold("2317", quantity=1000, average_cost=40.0)
    harness.hold("2603", quantity=1000, average_cost=30.0)

    await harness.show_account_history()

    output = screen.getvalue()
    assert "Warning: no live quote for 2317. Its price is the daily close of 2026-10-18 13:30, not the current price." in output
    assert "Warning: no price for 2603. It is valued at its average cost, with no unrealized PnL." in output
    assert "for 2330." not in output


async def test_the_menu_accepts_exactly_the_options_it_prints(screen: io.StringIO, monkeypatch) -> None:
    harness = build_harness()
    monkeypatch.setattr(interactive, "open_runtime", lambda: nullcontext(harness.runtime))
    asked: list[list[str]] = []

    def answer(question: str, choices: list[str] | None = None, **kwargs) -> str:
        asked.append(choices or [])
        return "0"

    with patch.object(Prompt, "ask", answer):
        await interactive.interactive_menu()

    printed = [line.split("]")[0].removeprefix("[") for line in screen.getvalue().splitlines() if line[:1] == "[" and "] " in line]
    assert printed == ["1", "2", "3", "4", "5", "6", "7", "0"]
    assert asked == [["0", "1", "2", "3", "4", "5", "6", "7"]]


async def test_ctrl_d_at_a_yes_no_prompt_cancels_the_option_and_places_no_order(screen: io.StringIO) -> None:
    harness = build_harness()
    harness.list_stock("2317", falling_history(100.0), realtime_price=98.0)

    def press_ctrl_d(*args, **kwargs) -> bool:
        raise EOFError

    with patch.object(Prompt, "ask", lambda *args, **kwargs: "2317"), patch.object(Confirm, "ask", press_ctrl_d):
        assert await interactive.run_menu_option("4", harness.runtime) is None

    assert "Analyse Specific Stocks cancelled." in screen.getvalue()
    assert harness.broker.placed == []
