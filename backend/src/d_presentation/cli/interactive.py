"""The CLI menu: one table of options drives what the menu prints, which choices it accepts and what each choice runs."""

import asyncio
import os
import sys
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from rich.panel import Panel

from a_domain.model.system.user import User
from a_domain.types.enums import ExecutionProvider, OrderMode, Permission
from a_domain.types.errors import ListingUnavailableError
from b_application.config.app_config import AppConfig
from b_application.schemas.pipeline_status import PipelineStatus
from d_presentation.cli import account_views, terminal, trading_views, user_views, valuation_views
from d_presentation.dependencies import STARTUP_REFUSALS, Runtime
from d_presentation.live_runtime import ReloadRefused, RuntimeSwitch, SettingsReload, SettingsReloaded, describe, open_runtime_switch

EXIT = "0"


@dataclass(frozen=True, kw_only=True)
class MenuOption:
    title: str
    description: tuple[str, ...]
    run: Callable[[Runtime, terminal.CliSession], Awaitable[PipelineStatus | None]]
    """The option's view. It returns the trading workflow's status, which the menu summarizes, or None."""

    may_submit_orders: bool = False
    """
    The option can send an order to the broker (menu 4 only for a BUY the user confirms). The menu adds a line saying
    what the current order mode does with its orders, and a real broker's warning names it.
    """


MENU = {
    "1": MenuOption(
        title="Run Full Cycle",
        description=(
            "Scan the full market after close.",
            "Build the technical watchlist.",
            "Analyse watchlist stocks with news and AI.",
            "Generate next-day trading signals.",
        ),
        run=lambda runtime, session: session.pipeline.run_full_cycle(built_in_strategy_id=session.built_in_strategy_id),
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
        run=lambda runtime, session: session.pipeline.run_intraday(built_in_strategy_id=session.built_in_strategy_id),
        may_submit_orders=True,
    ),
    "4": MenuOption(
        title="Analyse Specific Stocks",
        description=("Show the complete stock report.", "Allow manual watchlist addition.", "Allow explicit manual BUY override."),
        run=trading_views.analyse_specific_stocks,
        may_submit_orders=True,
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
        run=lambda runtime, session: account_views.show_account_history(session.pipeline),
    ),
    "8": MenuOption(
        title="Load Built-in Strategy",
        description=(
            "Use a built-in technical strategy for the runs this session starts.",
            "Saved settings and the Web API stay as they are.",
        ),
        run=lambda runtime, session: load_built_in_strategy(runtime, session),
    ),
}


async def interactive_menu() -> None:
    async with open_runtime_switch() as switch:
        with switch.hold() as opened:
            user = await user_views.sign_in(opened.runtime.signed_out)

        if user is None:
            return

        try:
            await run_menu(switch, user)

        finally:
            terminal.console.print("\n[yellow]Shutting down...[/yellow]")

    terminal.console.print("[bold green]System stopped.[/bold green]")


async def run_menu(switch: RuntimeSwitch, user: User) -> None:
    """
    One round per menu option. Before the menu prints, the settings files on disk are loaded when they changed, with a
    line saying so. The round then holds one runtime from the menu it prints to the option's summary, so the trading
    setup the menu shows (broker, order mode, the real-broker warning) is the one the chosen option runs on, and an
    edit made during an option waits for the next round. An option that may send an order looks at the files once
    more after the choice: settings that changed while the menu waited, a Web save included, print the menu again on
    them instead. The user is read again before each option; menu 8's strategy carries over to the next round while
    the settings still have it.
    """
    built_in_strategy_id: str | None = None

    while True:
        print_reload(await switch.reload())

        with switch.hold() as opened:
            runtime = opened.runtime
            built_in_strategy_id = still_built_in(runtime, built_in_strategy_id)
            session = session_for(runtime, user, built_in_strategy_id)
            choice = ask_menu_choice(runtime.config, session)

            if choice in (None, EXIT) or not await still_signed_in(runtime, session):
                return

            if MENU[choice].may_submit_orders and await reloaded(switch):
                terminal.console.print("[yellow]The settings changed while the menu waited. Choose again on them.[/yellow]")
                continue

            await run_menu_option(choice, runtime, session)
            built_in_strategy_id = session.built_in_strategy_id

        terminal.console.print("\n" + "=" * 50 + "\n")


async def reloaded(switch: RuntimeSwitch) -> bool:
    """
    Loads the settings files when they changed, saying so. True when the CLI runs on new settings now: in the CLI's
    process nothing else reloads, so the round's runtime is no longer the current one.
    """
    reload = await switch.reload()
    print_reload(reload)
    return isinstance(reload, SettingsReloaded)


def print_reload(reload: SettingsReload | None) -> None:
    """Nothing when the settings files did not change; one line for a reload; the problems for one the app refused."""
    match reload:
        case SettingsReloaded():
            terminal.console.print(f"[green]Settings reloaded: {describe(reload)}.[/green]")
        case ReloadRefused(problems=problems):
            terminal.console.print("[red]The settings files on disk would not start, so the CLI keeps its settings:[/red]")

            for problem in problems:
                terminal.console.print(f"  - {problem}", style="red", markup=False, highlight=False)
        case None:
            return


def still_built_in(runtime: Runtime, built_in_strategy_id: str | None) -> str | None:
    """Menu 8's strategy for this round, or None, with a line, when the reloaded settings no longer have it."""
    strategies = {strategy.strategy_id for strategy in runtime.config.technical.built_in_strategies}

    if built_in_strategy_id is None or built_in_strategy_id in strategies:
        return built_in_strategy_id

    terminal.console.print(
        f"[yellow]The settings no longer have the built-in {built_in_strategy_id}; runs use the saved settings.[/yellow]"
    )
    return None


def session_for(runtime: Runtime, user: User, built_in_strategy_id: str | None = None) -> terminal.CliSession:
    """The one way a CLI session is made, from the signed-in administrator: every menu option runs on their Pipeline."""
    return terminal.CliSession(user=user, pipeline=runtime.pipeline_for(user), built_in_strategy_id=built_in_strategy_id)


async def still_signed_in(runtime: Runtime, session: terminal.CliSession) -> bool:
    """
    Reads the user again before each menu option: a user deactivated, or no longer an administrator, since the CLI
    started loses it, and with it manual BUY and the real broker, at the next option.
    """
    user = await runtime.signed_out.load_user(session.user.user_id)

    if user is not None and Permission.USE_CLI in user.permissions:
        return True

    terminal.console.print("[red]You were signed out: your account is deactivated or no longer an administrator.[/red]")
    return False


def ask_menu_choice(config: AppConfig, session: terminal.CliSession) -> str | None:
    print_menu(config, session)
    choice = terminal.ask_user("Select an option", choices=[EXIT, *MENU])

    if choice is None:
        terminal.console.print("\n[yellow]Exiting.[/yellow]")

    return choice


async def run_menu_option(choice: str, runtime: Runtime, session: terminal.CliSession) -> PipelineStatus | None:
    """
    Runs the chosen option on the session's Pipeline and summarizes the trading workflow it ran. Ctrl-D at one of its
    y/n prompts cancels it.
    """
    option = MENU[choice]

    try:
        status = await option.run(runtime, session)
    except EOFError:
        terminal.console.print(f"\n[yellow]{option.title} cancelled.[/yellow]")
        return None
    except ListingUnavailableError as error:
        terminal.console.print(f"[red]{error}[/red]")
        return None

    if status is not None:
        trading_views.print_context_summary(status)

    return status


def print_menu(config: AppConfig, session: terminal.CliSession) -> None:
    terminal.console.print(f"Signed in:          {session.user.username} ({session.user.role.value})")
    print_trading_setup(config)
    strategy = session.built_in_strategy_id
    terminal.console.print(f"Technical strategy: {f'built-in {strategy}, this session only' if strategy else 'saved settings'}")
    terminal.console.print("")

    for key, option in MENU.items():
        terminal.console.print(f"[{key}] {option.title}")

        for line in option.description:
            terminal.console.print(f"    {line}")

        if option.may_submit_orders:
            terminal.console.print(f"    {order_mode_effect(config)}")

        terminal.console.print("")

    terminal.console.print(f"[{EXIT}] Exit")


async def load_built_in_strategy(runtime: Runtime, session: terminal.CliSession) -> None:
    """Menu 8: one of the built-in strategies for this session's runs, or cancel and keep the current choice."""
    strategies = runtime.config.technical.built_in_strategies

    for number, strategy in enumerate(strategies, start=1):
        terminal.console.print(f"[{number}] {strategy.name}")

    terminal.console.print(f"[{EXIT}] Cancel")
    choice = terminal.ask_user(
        "Load which built-in strategy", choices=[EXIT, *(str(number) for number in range(1, len(strategies) + 1))]
    )

    if choice in (None, EXIT):
        terminal.console.print("\n[yellow]Cancelled. The strategy is unchanged.[/yellow]")
        return None

    strategy = strategies[int(choice) - 1]
    session.built_in_strategy_id = strategy.strategy_id
    terminal.console.print(f"Runs in this session use the built-in {strategy.name} strategy. Saved settings are unchanged.")
    return None


def print_trading_setup(config: AppConfig) -> None:
    real_broker = config.trading.execution_provider != ExecutionProvider.MOCK
    broker = terminal.format_label(config.trading.execution_provider.value)
    mode = terminal.format_label(config.trading.order_mode.value)

    terminal.console.print(f"Environment:        {terminal.format_label(config.environment.value)}")
    terminal.console.print(f"Execution Provider: {broker}")
    terminal.console.print(f"Account:            {'the broker default stock account' if real_broker else 'your mock account'}")
    terminal.console.print(f"Orders:             {mode}")

    if not real_broker:
        return

    server = "SIMULATION (paper trading)" if config.environment.shioaji_simulation else "PRODUCTION: REAL ACCOUNT, REAL MONEY"
    order_menus = ", ".join(key for key, option in MENU.items() if option.may_submit_orders)
    orders = (
        f"menus {order_menus} send orders to the broker"
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

    except STARTUP_REFUSALS as error:
        terminal.console.print(str(error), style="red", markup=False, highlight=False)
        exit_code = 1

    finally:
        os._exit(exit_code)
