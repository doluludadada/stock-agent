"""
The CLI loads the settings files again before each menu round, never during an option, and says so in one line. An
option that may send an order looks once more after the choice, so a save made while the menu waited is not missed.
"""

import io
import shutil
from pathlib import Path
from unittest.mock import patch

import pytest
from rich.console import Console
from rich.prompt import Confirm, Prompt
from support.harness import ADMINISTRATOR, ADMINISTRATOR_PASSWORD, build_harness, falling_history, open_harness_switch

from a_domain.types.enums import OrderStatus
from d_presentation.cli import interactive, terminal

pytestmark = pytest.mark.asyncio

REPOSITORY_CONFIG = Path(__file__).resolve().parents[2] / "config"


@pytest.fixture
def screen(monkeypatch: pytest.MonkeyPatch) -> io.StringIO:
    output = io.StringIO()
    monkeypatch.setattr(terminal, "console", Console(file=output, width=250))
    return output


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A copy of config/, with a placeholder key for the active AI provider, which every reload needs."""
    shutil.copytree(REPOSITORY_CONFIG, tmp_path / "config")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "placeholder")
    return tmp_path


def edit(project: Path, old: str, new: str) -> None:
    path = project / "config" / "appsetting.yaml"
    path.write_text(path.read_text(encoding="utf-8").replace(old, new, 1), encoding="utf-8")


def answers(project: Path, during_the_option: tuple[str, str], *, choices: list[str]):
    """
    Signs in, picks `choices` in turn at the menu, orders on the mock account, and edits the file on disk while menu 4
    asks for its stocks.
    """
    remaining = list(choices)

    def ask(question: str, *args, **kwargs) -> str:
        if kwargs.get("password"):
            return ADMINISTRATOR_PASSWORD

        if question == "Username or email":
            return ADMINISTRATOR.username

        if question.startswith("Select an option"):
            return remaining.pop(0)

        if question == "Order on":
            return "mock"

        edit(project, *during_the_option)
        return "2317"

    return ask


def confirm(question: str, *args, **kwargs) -> bool:
    return question.startswith("BUY ")


async def test_an_edit_during_an_option_waits_for_the_next_round_which_reloads_and_says_so(
    project: Path, screen: io.StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    harness = build_harness(settings_root=project, sinopac=True)
    harness.list_stock("2317", falling_history(100.0), realtime_price=98.0)
    monkeypatch.setattr(interactive, "open_runtime_switch", lambda: open_harness_switch(harness))
    ask = answers(project, ("max_order_value: 100000", "max_order_value: 90000"), choices=["4", "0"])

    with patch.object(Prompt, "ask", ask), patch.object(Confirm, "ask", confirm):
        await interactive.interactive_menu()

    output = screen.getvalue()
    [order] = harness.journal.orders.values()
    assert (order.status, [placed.stock_id for placed in harness.broker.placed]) == (OrderStatus.FILLED, ["2317"])
    assert output.count("Settings reloaded: appsetting.yaml") == 1
    reloaded = output.index("Settings reloaded: appsetting.yaml")
    assert "each BUY at most 100,000 NT$" in output[:reloaded] and "each BUY at most 90,000 NT$" in output[reloaded:]


async def test_an_edit_on_disk_the_app_would_refuse_keeps_the_cli_on_its_settings_and_says_where(
    project: Path, screen: io.StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    harness = build_harness(settings_root=project, sinopac=True)
    harness.list_stock("2317", falling_history(100.0), realtime_price=98.0)
    monkeypatch.setattr(interactive, "open_runtime_switch", lambda: open_harness_switch(harness))
    ask = answers(project, ("max_order_value: 100000", "max_order_value: plenty"), choices=["4", "4", "0"])

    with patch.object(Prompt, "ask", ask), patch.object(Confirm, "ask", confirm):
        await interactive.interactive_menu()

    output = screen.getvalue()
    refused = output.index("The settings files on disk would not start, so the CLI keeps its settings:")
    assert "trading.max_order_value: Input should be" in output[refused:] and "appsetting.yaml line " in output[refused:]
    assert "each BUY at most 100,000 NT$" in output[refused:] and "Settings reloaded" not in output
    assert output.count("would not start") == 1, "the same refused files are not opened and reported again each round"


async def test_a_save_made_while_the_menu_waits_reaches_the_ordering_option_chosen_after_it(
    project: Path, screen: io.StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    harness = build_harness(settings_root=project, sinopac=True)
    harness.list_stock("2317", falling_history(100.0), realtime_price=98.0)
    monkeypatch.setattr(interactive, "open_runtime_switch", lambda: open_harness_switch(harness))
    remaining = ["4", "4", "0"]

    def ask(question: str, *args, **kwargs) -> str:
        if kwargs.get("password"):
            return ADMINISTRATOR_PASSWORD

        if question == "Username or email":
            return ADMINISTRATOR.username

        if question == "Order on":
            return "shioaji"

        if not question.startswith("Select an option"):
            return "2317"

        if len(remaining) == 3:
            edit(project, "max_order_value: 100000", "max_order_value: 1")

        return remaining.pop(0)

    with patch.object(Prompt, "ask", ask), patch.object(Confirm, "ask", confirm):
        await interactive.interactive_menu()

    output = screen.getvalue()
    assert (harness.real_broker.placed, harness.broker.placed) == ([], [])
    again = output.index("The settings changed while the menu waited. Choose again on them.")
    assert "each BUY at most 100,000 NT$" in output[:again] and "each BUY at most 1 NT$" in output[again:]
    assert output.index("each BUY at most 1 NT$", again) < output.index("Stock Reports") < output.index("Each BUY at most 1 NT$")
