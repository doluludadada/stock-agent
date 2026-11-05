"""
The terminal every CLI view shares: the one console, the prompts, how values print, and what one CLI session
remembers between menu options. Views use `terminal.console` through this module, so a test or a harness that swaps
the console here sees every view's output.
"""

from dataclasses import dataclass
from datetime import datetime
from signal import SIGINT, default_int_handler, signal as set_signal_handler

from rich.console import Console
from rich.prompt import Confirm, Prompt

from c_infrastructure.system.market_clock import TAIWAN_TIMEZONE

console = Console()


@dataclass
class CliSession:
    """
    What one CLI session remembers between menu options: the built-in strategy the user loaded for the runs it starts,
    or None for the saved settings. It lives only as long as the CLI process: no saved setting and no Web API request
    sees it.
    """

    built_in_strategy_id: str | None = None


def ask_user(question: str, choices: list[str] | None = None) -> str | None:
    """Returns None when the user presses Ctrl-C or Ctrl-D at the prompt."""
    # asyncio.run turns Ctrl-C into a cancel of the next workflow, so the prompt restores Python's own handler while it waits.
    asyncio_sigint_handler = set_signal_handler(SIGINT, default_int_handler)

    try:
        return Prompt.ask(question, choices=choices)
    except KeyboardInterrupt, EOFError:
        return None
    finally:
        set_signal_handler(SIGINT, asyncio_sigint_handler)


def confirm(question: str) -> bool:
    """A y/n question that Enter answers no. Ctrl-D raises EOFError, which the menu reports as a cancelled option."""
    return Confirm.ask(question, default=False)


def ask_stock_ids() -> list[str] | None:
    """The stock IDs the user typed, or None after saying the prompt was cancelled or left empty."""
    raw_symbols = ask_user("Enter stock IDs separated by space or comma")

    if raw_symbols is None:
        console.print("\n[yellow]Operation cancelled.[/yellow]")
        return None

    stock_ids = raw_symbols.replace(",", " ").split()

    if not stock_ids:
        console.print("[yellow]No stock IDs entered.[/yellow]")
        return None

    return stock_ids


def format_label(value: str) -> str:
    return value.replace("_", " ").upper()


def format_number(value: float | None) -> str:
    if value is None:
        return "-"

    return f"{value:.2f}"


def format_optional_int(value: int | None) -> str:
    if value is None:
        return "-"

    return str(value)


def format_datetime(value: datetime | None) -> str:
    if value is None:
        return "-"

    return f"{value.astimezone(TAIWAN_TIMEZONE):%Y-%m-%d %H:%M}"
