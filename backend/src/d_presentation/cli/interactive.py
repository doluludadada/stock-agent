# backend/src/d_presentation/cli/interactive.py

import asyncio
import os
import sys

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, IntPrompt, Prompt
from rich.table import Table

from b_application.schemas.pipeline_status import PipelineStatus
from b_application.pipeline import Pipeline
from d_presentation.cli.cli_container import build_cli_orchestrator

console = Console()


async def interactive_menu() -> None:
    console.print(Panel.fit("[bold cyan]TW-Stock-Alpha-Agent CLI[/bold cyan]", border_style="cyan"))
    console.print("[yellow]Booting up and wiring dependencies...[/yellow]")

    runtime = await build_cli_orchestrator()
    workflow = runtime.workflow

    console.print("[green]System Ready![/green]\n")

    try:
        while True:
            _print_menu()

            try:
                choice = Prompt.ask("Select an option", choices=["0", "1", "2", "3", "4"])
            except (KeyboardInterrupt, EOFError):
                console.print("\n[yellow]Exiting...[/yellow]")
                return

            if choice == "0":
                break

            context: PipelineStatus | None = None

            if choice == "1":
                context = await workflow.run_full_cycle()
            elif choice == "2":
                context = await workflow.run_buzz_scan()
            elif choice == "3":
                context = await workflow.run_intraday()
            elif choice == "4":
                context = await _run_specific_stock_flow(workflow)

            if context is not None:
                _print_context_summary(context)

            console.print("\n" + "=" * 50 + "\n")
    finally:
        console.print("\n[yellow]Shutting down...[/yellow]")
        await runtime.shutdown()
        console.print("[bold green]System stopped.[/bold green]")


def _print_menu() -> None:
    console.print("[1] Run Full Cycle")
    console.print("    Scan the full market after close. Build the technical watchlist.")
    console.print("    Analyse watchlist stocks with news and AI. Generate next-day trading signals.")
    console.print("    Never execute closed-market orders.")
    console.print("[2] Scan Social Buzz")
    console.print("    Find actively discussed stocks. Add qualified stocks to the watchlist.")
    console.print("    Analyse them and generate signals. Execute only when market and risk checks allow.")
    console.print("[3] Run Intraday Trading")
    console.print("    Load held positions and watchlist. Revalidate current data, technicals and AI.")
    console.print("    Generate signals and submit mock orders when allowed.")
    console.print("[4] Analyse Specific Stocks")
    console.print("    Show the complete stock report. Allow manual watchlist addition or manual BUY override.")
    console.print("[0] Exit")


async def _run_specific_stock_flow(workflow: Pipeline) -> PipelineStatus | None:
    try:
        raw_symbols = Prompt.ask("Enter stock IDs separated by space or comma")
    except (KeyboardInterrupt, EOFError):
        console.print("\n[yellow]Operation cancelled.[/yellow]")
        return None

    stock_ids = _parse_stock_ids(raw_symbols)
    if not stock_ids:
        console.print("[yellow]No stock IDs entered.[/yellow]")
        return None

    context = await workflow.analyse_specific_stocks(stock_ids)
    _print_stock_reports(context)

    if not context.all_stocks:
        return context

    if context.watchlist and Confirm.ask("Add passing stocks to manual watchlist?", default=False):
        await workflow.add_manual_watchlist(context.watchlist)

    if Confirm.ask("Submit manual BUY override for loaded stocks?", default=False):
        quantity = IntPrompt.ask("Quantity per stock", default=1)
        context = await workflow.execute_manual_buy_override(
            [stock.stock_id for stock in context.all_stocks],
            quantity,
            context=context,
        )

    return context


def _parse_stock_ids(raw_symbols: str) -> list[str]:
    return [symbol.strip() for symbol in raw_symbols.replace(",", " ").split() if symbol.strip()]


def _print_context_summary(context: PipelineStatus) -> None:
    console.print("[bold green]Execution Complete[/bold green]")
    console.print(
        f"Scanned={context.stats.total_scanned}, "
        f"Survivors={len(context.survivors)}, "
        f"Signals={context.stats.signals_generated}, "
        f"Orders={context.stats.orders_submitted}, "
        f"Errors={context.stats.total_errors}"
    )

    signals = [
        *context.exit_signals,
        *context.buy_signals,
        *context.hold_signals,
    ]

    if not signals:
        console.print("No trading signals generated.")
        return

    table = Table(title="Signals")
    table.add_column("Stock")
    table.add_column("Action")
    table.add_column("Score", justify="right")
    table.add_column("Qty", justify="right")
    table.add_column("Reason")

    for signal in signals:
        table.add_row(
            signal.stock_id,
            signal.action.value.upper(),
            str(signal.score),
            str(signal.quantity),
            signal.reason,
        )

    console.print(table)


def _print_stock_reports(context: PipelineStatus) -> None:
    if not context.all_stocks:
        console.print("[yellow]No stocks loaded.[/yellow]")
        return

    table = Table(title="Stock Reports")
    table.add_column("Stock")
    table.add_column("Name")
    table.add_column("Price", justify="right")
    table.add_column("Tech", justify="right")
    table.add_column("AI", justify="right")
    table.add_column("Combined", justify="right")
    table.add_column("Hard Failures")
    table.add_column("AI Summary")

    for stock in context.all_stocks:
        report = stock.analysis_report
        table.add_row(
            stock.stock_id,
            stock.name or "",
            _format_number(stock.current_price),
            _format_optional_int(stock.technical_score),
            _format_optional_int(stock.ai_score),
            str(stock.combined_score),
            ", ".join(stock.hard_failures) or "-",
            report.summary if report else "-",
        )

    console.print(table)


def _format_number(value: float | None) -> str:
    if value is None:
        return "-"

    return f"{value:.2f}"


def _format_optional_int(value: int | None) -> str:
    if value is None:
        return "-"

    return str(value)


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    try:
        asyncio.run(interactive_menu())
    except (KeyboardInterrupt, asyncio.CancelledError, SystemExit):
        pass
    finally:
        os._exit(0)
