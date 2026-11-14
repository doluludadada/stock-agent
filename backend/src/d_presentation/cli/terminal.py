"""
The terminal every CLI view shares: the one console, the prompts, how values print, and what one CLI session
remembers between menu options. Views use `terminal.console` through this module, so a test or a harness that swaps
the console here sees every view's output.
"""

import asyncio
import os
import sys
from collections.abc import Coroutine
from dataclasses import dataclass
from datetime import datetime
from signal import SIGINT, default_int_handler, signal as set_signal_handler
from typing import NoReturn

from pydantic import SecretStr
from rich.console import Console
from rich.prompt import Confirm, Prompt

from a_domain.model.system.user import User
from b_application.pipeline import Pipeline
from c_infrastructure.system.market_clock import TAIWAN_TIMEZONE
from d_presentation.dependencies import STARTUP_REFUSALS

console = Console()


def run_to_exit(command: Coroutine[None, None, int], *refusals: type[Exception]) -> NoReturn:
    """
    Runs a command line's coroutine and ends the process with the exit code it answers, or 1 after printing a startup
    refusal, one of `refusals` or an unexpected error. The broker's SDK can leave a thread running that would hold the
    interpreter at exit, so the process ends here; anything unexpected is printed first, since nothing prints after.
    """
    exit_code = 1

    try:
        exit_code = asyncio.run(command)
    except SystemExit as stop:
        exit_code = stop.code if isinstance(stop.code, int) else 1
    except (*STARTUP_REFUSALS, *refusals) as error:
        console.print(str(error), style="red", markup=False, highlight=False)
    except Exception:
        console.print_exception()
    finally:
        sys.stdout.flush()
        os._exit(exit_code)


@dataclass
class CliSession:
    """
    What one CLI session remembers between menu options: the signed-in administrator, the Pipeline built for them,
    which every menu option runs on, and the built-in strategy the user loaded for the runs it starts, or None for the
    saved settings. It lives only as long as the CLI process: no saved setting and no Web API request sees it.
    """

    user: User
    pipeline: Pipeline
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


def ask_secret(question: str) -> SecretStr | None:
    """A hidden answer, such as a password. None when the user presses Ctrl-C or Ctrl-D at the prompt."""
    asyncio_sigint_handler = set_signal_handler(SIGINT, default_int_handler)

    try:
        return SecretStr(Prompt.ask(question, password=True))
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
