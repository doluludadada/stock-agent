import io
from contextlib import nullcontext
from unittest.mock import patch

import pytest
from rich.console import Console
from rich.prompt import Prompt
from support.harness import MARKET_CLOSED, build_harness, falling_history, rising_history

from a_domain.types.enums import OrderStatus
from d_presentation.cli import interactive

pytestmark = pytest.mark.asyncio


@pytest.fixture
def screen(monkeypatch) -> io.StringIO:
    output = io.StringIO()
    monkeypatch.setattr(interactive, "console", Console(file=output, width=250))
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
