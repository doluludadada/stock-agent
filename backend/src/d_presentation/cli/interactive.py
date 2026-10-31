"""The CLI menu: one table of options drives what the menu prints, which choices it accepts and what each choice runs."""

import asyncio
import os
import sys
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from rich.panel import Panel

from a_domain.types.enums import ExecutionProvider, OrderMode
from b_application.config.app_config import AppConfig
from b_application.schemas.pipeline_status import PipelineStatus
from c_infrastructure.database.db_connector import OutdatedDatabaseError
from d_presentation.cli import account_views, terminal, trading_views, valuation_views
from d_presentation.dependencies import Runtime, TradingSetupError, open_runtime

EXIT = "0"


@dataclass(frozen=True, kw_only=True)
class MenuOption:
    title: str
    description: tuple[str, ...]
    run: Callable[[Runtime], Awaitable[PipelineStatus | None]]
    """The option's view. It returns the trading workflow's status, which the menu summarizes, or None."""

    may_submit_orders: bool = False
    """The menu adds a line saying what the current order mode does with this option's orders."""


MENU = {
    "1": MenuOption(
        title="Run Full Cycle",
        description=(
            "Scan the full market after close.",
            "Build the technical watchlist.",
            "Analyse watchlist stocks with news and AI.",
            "Generate next-day trading signals.",
        ),
        run=lambda runtime: runtime.pipeline.run_full_cycle(),
    ),
    "2": MenuOption(
        title="Scan Social Buzz",
        description=("Find actively discussed stocks.", "Analyse qualified buzz stocks."),
        run=trading_views.scan_social_buzz,
        may_submit_orders=True,
    ),
    "3": MenuOption(
        title="Run Intraday Trading",
        description=("Revalidate positions and active watchlist stocks.", "Generate signals."),
        run=lambda runtime: runtime.pipeline.run_intraday(),
        may_submit_orders=True,
    ),
    "4": MenuOption(
        title="Analyse Specific Stocks",
        description=("Show the complete stock report.", "Allow manual watchlist addition.", "Allow explicit manual BUY override."),
        run=trading_views.analyse_specific_stocks,
    ),
    "5": MenuOption(
        title="Value Specific Stocks",
        description=(
            "Show TTM EPS from MOPS filings, the official close and the current P/E.",
            "Ask your target P/E; show three fair-price scenarios and an AI explanation.",
            "Read-only: never touches the watchlist or orders.",
        ),
        run=valuation_views.value_specific_stocks,
    ),
    "6": MenuOption(
        title="Scan Undervalued Stocks",
        description=(
            "Find stocks priced below EPS x your target P/E.",
            "Optionally confirm the matches with the active technical strategy.",
            "Read-only: never touches the watchlist or orders.",
        ),
        run=valuation_views.scan_undervalued_stocks,
    ),
    "7": MenuOption(
        title="Account History",
        description=(
            "Show cash, positions and unrealized PnL at the latest prices.",
            "Show the equity curve and the account as of a date. Never places orders.",
        ),
        run=account_views.show_account_history,
    ),
}


async def interactive_menu() -> None:
    async with open_runtime() as runtime:
        try:
            while (choice := ask_menu_choice(runtime.config)) not in (None, EXIT):
                await run_menu_option(choice, runtime)
                terminal.console.print("\n" + "=" * 50 + "\n")

        finally:
            terminal.console.print("\n[yellow]Shutting down...[/yellow]")

    terminal.console.print("[bold green]System stopped.[/bold green]")


def ask_menu_choice(config: AppConfig) -> str | None:
    print_menu(config)
    choice = terminal.ask_user("Select an option", choices=[EXIT, *MENU])

    if choice is None:
        terminal.console.print("\n[yellow]Exiting.[/yellow]")

    return choice


async def run_menu_option(choice: str, runtime: Runtime) -> PipelineStatus | None:
    """Runs the chosen option and summarizes the trading workflow it ran. Ctrl-D at one of its y/n prompts cancels it."""
    option = MENU[choice]

    try:
        status = await option.run(runtime)
    except EOFError:
        terminal.console.print(f"\n[yellow]{option.title} cancelled.[/yellow]")
        return None

    if status is not None:
        trading_views.print_context_summary(status)

    return status


def print_menu(config: AppConfig) -> None:
    print_trading_setup(config)
    terminal.console.print("")

    for key, option in MENU.items():
        terminal.console.print(f"[{key}] {option.title}")

        for line in option.description:
            terminal.console.print(f"    {line}")

        if option.may_submit_orders:
            terminal.console.print(f"    {order_mode_effect(config)}")

        terminal.console.print("")

    terminal.console.print(f"[{EXIT}] Exit")


def print_trading_setup(config: AppConfig) -> None:
    real_broker = config.trading.execution_provider != ExecutionProvider.MOCK
    broker = terminal.format_label(config.trading.execution_provider.value)
    mode = terminal.format_label(config.trading.order_mode.value)

    terminal.console.print(f"Environment:        {terminal.format_label(config.environment.value)}")
    terminal.console.print(f"Execution Provider: {broker}")
    terminal.console.print(
        f"Account:            {'the broker default stock account' if real_broker else config.mock_trading.account_id}"
    )
    terminal.console.print(f"Orders:             {mode}")

    if not real_broker:
        return

    server = "SIMULATION (paper trading)" if config.shioaji.simulation else "PRODUCTION: REAL ACCOUNT, REAL MONEY"
    orders = (
        "menus 2 and 3 and a confirmed manual BUY send orders to the broker"
        if config.trading.order_mode == OrderMode.LIVE
        else "no order is sent; cash and positions are read from the broker"
    )
    terminal.console.print(Panel(f"{broker} {server}\nOrders {mode}: {orders}", title="REAL BROKER", style="bold red"))


def order_mode_effect(config: AppConfig) -> str:
    mode = terminal.format_label(config.trading.order_mode.value)
    broker = terminal.format_label(config.trading.execution_provider.value)

    return {
        OrderMode.MOCK_ONLY: f"May submit orders to the mock broker (order mode {mode}).",
        OrderMode.LIVE: f"May submit orders to the {broker} broker (order mode {mode}).",
        OrderMode.DISABLED: f"Would submit orders, but order mode {mode} records each one REJECTED and sends none.",
    }[config.trading.order_mode]


if __name__ == "__main__":
    exit_code = 0

    try:
        if sys.platform == "win32":
            asyncio.run(interactive_menu(), loop_factory=asyncio.SelectorEventLoop)
        else:
            asyncio.run(interactive_menu())

    except KeyboardInterrupt, asyncio.CancelledError, SystemExit:
        pass

    except (OutdatedDatabaseError, TradingSetupError) as error:
        terminal.console.print(str(error), style="red", markup=False, highlight=False)
        exit_code = 1

    finally:
        os._exit(exit_code)
