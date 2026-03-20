# backend/src/d_presentation/cli/interactive.py

import asyncio
import sys

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt

from b_application.schemas.pipeline_context import PipelineContext
from d_presentation.cli.cli_container import build_cli_orchestrator

console = Console()


async def interactive_menu():
    console.print(Panel.fit("[bold cyan]TW-Stock-Alpha-Agent CLI[/bold cyan]", border_style="cyan"))

    console.print("[yellow]Booting up and wiring dependencies...[/yellow]")
    orchestrator = await build_cli_orchestrator()
    console.print("[green]System Ready![/green]\n")

    try:
        while True:
            console.print("[1] Run Full Cycle (WARNING: Scans 1700+ stocks, slow!)")
            console.print("[2] Phase 1: Run Nightly Tech Scan (Update DB)")
            console.print("[3] Phase 2: Run Morning Buzz Scan (Update DB)")
            console.print("[4] Phase 3: Run Intraday Pipeline (Process DB Watchlists)")
            console.print("[5] Target Mode: Manually test a specific stock (e.g., 2330)")
            console.print("[0] Exit")

            try:
                choice = Prompt.ask("Select an option", choices=["0", "1", "2", "3", "4", "5"])
            except (KeyboardInterrupt, EOFError):
                console.print("\n[yellow]Exiting...[/yellow]")
                return

            if choice == "0":
                break

            context = PipelineContext()

            if choice == "1":
                await orchestrator.run_full_cycle()
            elif choice == "2":
                await orchestrator.run_nightly(context)
            elif choice == "3":
                await orchestrator.run_buzz_scan(context)
            elif choice == "4":
                await orchestrator.run_intraday(context)
            elif choice == "5":
                try:
                    symbols = Prompt.ask("Enter stock symbols separated by space (e.g. '2330 2317')")
                except (KeyboardInterrupt, EOFError):
                    console.print("\n[yellow]Operation cancelled.[/yellow]")
                    continue
                symbol_list = [s.strip() for s in symbols.split()]
                context.manual_symbols = symbol_list
                await orchestrator.run_intraday(context)

            console.print("\n[bold green]Execution Complete![/bold green]")
            if context.buy_signals:
                for sig in context.buy_signals:
                    console.print(f"💰 Signal Generated: {sig.action.value} {sig.stock_id} (Score: {sig.score})")
            else:
                console.print("No actionable signals generated.")
            print("\n" + "=" * 50 + "\n")
    finally:
        await orchestrator.shutdown()


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    try:
        asyncio.run(interactive_menu())
    except (KeyboardInterrupt, asyncio.CancelledError):
        # Silence the traceback when exiting via Ctrl+C
        sys.exit(0)
