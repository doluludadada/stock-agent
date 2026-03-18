# backend/src/d_presentation/cli/interactive.py
import argparse
import asyncio
import sys
from pathlib import Path
from typing import Set

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from b_application.schemas.pipeline_context import PipelineContext
from d_presentation.cli.cli_config import build_pipeline
from d_presentation.dependencies.core import get_db_connector, get_settings, get_logger
async def main():
    parser = argparse.ArgumentParser(description="Stock Agent Interactive CLI")
    parser.add_argument("--symbols", type=str, help="Comma-separated stock symbols (e.g. 2330,2317)", default="")
    parser.add_argument("--env", type=str, help="Environment override (DEV, TEST, LIVE)", default="")
    args = parser.parse_args()

    console = Console()
    console.print(Panel("[bold cyan]Stock Agent[/bold cyan] Pipeline Engine", border_style="cyan"))

    symbols_list = [s.strip() for s in args.symbols.split(",") if s.strip()]
    context = PipelineContext(manual_symbols=symbols_list)

    if symbols_list:
        console.print(f"[dim]Analyzing custom symbols: {symbols_list}[/dim]\n")

    try:
        config = get_settings()
        logger = get_logger.__wrapped__(config=config)
        connector = get_db_connector.__wrapped__(config=config, logger=logger)
        await connector.init_db()
        
        pipeline = build_pipeline(env_override=args.env)

        with console.status("[bold green]Agent Pipeline Running... fetching data, analyzing patterns, and consulting AI...", spinner="aesthetic"):
            await pipeline.execute(context)

        console.print("\n[bold green]✅ Pipeline finished successfully![/bold green]\n")

        # -------------------------------------------------------------
        # Generate the Report Table
        # -------------------------------------------------------------
        table = Table(title="Analysis Summary Report", show_header=True, header_style="bold magenta")
        table.add_column("Symbol", style="cyan", justify="left")
        table.add_column("Price", justify="right")
        table.add_column("Tech Status", justify="center")
        table.add_column("AI Score", justify="center")
        table.add_column("Final Signal", justify="center")

        # Aggregate all unique symbols from the pipeline context
        all_symbol_ids: Set[str] = set()
        
        for pool in [context.candidates, context.priced, context.survivors, context.analysed]:
            for s in pool:
                all_symbol_ids.add(s.stock_id)

        # Map to find the "deepest" iteration of each stock object
        stock_map = {}
        for pool in [context.candidates, context.priced, context.survivors, context.analysed]:
            for s in pool:
                stock_map[s.stock_id] = s
                
        # Find which generated signals
        buy_signals = {sig.stock_id: sig.action for sig in context.buy_signals}
        exit_signals = {sig.stock_id: sig.action for sig in context.exit_signals}

        if not all_symbol_ids:
            table.add_row("N/A", "N/A", "No symbols processed", "N/A", "N/A")
        else:
            for sid in sorted(all_symbol_ids):
                stock = stock_map[sid]

                price_str = f"{stock.current_price:.2f}" if stock.current_price else "--"

                tech_status = "[red]Failed[/red]"
                if stock in context.survivors:
                    tech_status = "[green]Pass[/green]"

                ai_score = str(stock.composite_score) if getattr(stock, 'composite_score', None) is not None else "--"
                
                signal_str = "[dim]HOLD[/dim]"
                if sid in buy_signals:
                    signal_str = f"[bold green]{buy_signals[sid]}[/bold green]"
                elif sid in exit_signals:
                    signal_str = f"[bold red]{exit_signals[sid]}[/bold red]"

                table.add_row(sid, price_str, tech_status, ai_score, signal_str)

        console.print(table)

        # -------------------------------------------------------------
        # Final Stats
        # -------------------------------------------------------------
        console.print(f"\n[bold]Orders Submitted:[/bold] {context.orders_submitted}")
        errors = context.stats.errors
        if errors:
            console.print(f"[bold red]Errors Encountered ({len(errors)}):[/bold red]")
            for err in errors:
                console.print(f"  - {err}")

    except Exception as e:
        console.print(f"\n[bold red]Pipeline failed to run:[/bold red] {e}")


if __name__ == "__main__":
    asyncio.run(main())
