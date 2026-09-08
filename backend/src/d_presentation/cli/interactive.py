# backend/src/d_presentation/cli/interactive.py

import asyncio
import os
import sys

from rich.console import Console
from rich.prompt import Confirm, Prompt
from rich.table import Table

from a_domain.model.market.stock import Stock
from a_domain.types.enums import WatchlistType
from b_application.pipeline import Pipeline
from b_application.schemas.config import AppConfig
from b_application.schemas.pipeline_status import PipelineStatus
from b_application.use_cases.trade.manual_buy import ManualBuy
from b_application.use_cases.trade.watch_stocks import WatchStocks
from d_presentation.cli.cli_container import build_cli_orchestrator

console = Console()

# TODO:simplify it and catch only KeyboardInterrupt locally
USER_CANCELLED_EXCEPTIONS = (KeyboardInterrupt, EOFError)


async def interactive_menu() -> None:
    runtime = await build_cli_orchestrator()

    try:
        while True:
            print_menu(runtime.config)

            choice = ask_menu_choice()

            if choice is None or choice == "0":
                return

            context = await execute_menu_choice(
                choice=choice,
                pipeline=runtime.pipeline,
                watch_stocks=runtime.watch_stocks,
                manual_buy=runtime.manual_buy,
            )

            if context is not None:
                print_context_summary(context)

            console.print("\n" + "=" * 50 + "\n")

    finally:
        console.print("\n[yellow]Shutting down...[/yellow]")
        await runtime.shutdown()
        console.print("[bold green]System stopped.[/bold green]")


def ask_menu_choice() -> str | None:
    try:
        return Prompt.ask(
            "Select an option",
            choices=["0", "1", "2", "3", "4"],
        )
    except USER_CANCELLED_EXCEPTIONS:
        console.print("\n[yellow]Exiting.[/yellow]")
        return None


async def execute_menu_choice(
    choice: str,
    pipeline: Pipeline,
    watch_stocks: WatchStocks,
    manual_buy: ManualBuy,
) -> PipelineStatus | None:
    if choice == "1":
        return await pipeline.run_full_cycle()

    if choice == "2":
        return await run_buzz_scan(pipeline)

    if choice == "3":
        return await run_intraday(pipeline)

    if choice == "4":
        return await run_specific_stock_flow(
            pipeline=pipeline,
            watch_stocks=watch_stocks,
            manual_buy=manual_buy,
        )

    return None


async def run_buzz_scan(
    pipeline: Pipeline,
) -> PipelineStatus | None:
    context = await pipeline.run_buzz_scan()

    if context is None:
        console.print("[yellow]Social buzz pipeline is not implemented yet.[/yellow]")

    return context


async def run_intraday(
    pipeline: Pipeline,
) -> PipelineStatus:
    return await pipeline.run_intraday()


def print_menu(config: AppConfig) -> None:
    console.print(f"Environment:        {format_label(config.environment.value)}")
    console.print(f"Execution Provider: {format_label(config.trading.execution_provider.value)}")
    console.print(f"Account:            {config.mock_trading.account_id}")
    console.print(f"Orders:             {format_label(config.trading.order_mode.value)}")
    console.print("")

    console.print("[1] Run Full Cycle")
    console.print("    Scan the full market after close.")
    console.print("    Build the technical watchlist.")
    console.print("    Analyse watchlist stocks with news and AI.")
    console.print("    Generate next-day trading signals.")
    console.print("")

    console.print("[2] Scan Social Buzz")
    console.print("    Find actively discussed stocks.")
    console.print("    Analyse qualified buzz stocks.")
    console.print("")

    console.print("[3] Run Intraday Trading")
    console.print("    Revalidate positions and active watchlist stocks.")
    console.print("    Generate signals and permitted orders.")
    console.print("")

    console.print("[4] Analyse Specific Stocks")
    console.print("    Show the complete stock report.")
    console.print("    Allow manual watchlist addition.")
    console.print("    Allow explicit manual BUY override.")
    console.print("")

    console.print("[0] Exit")


async def run_specific_stock_flow(
    pipeline: Pipeline,
    watch_stocks: WatchStocks,
    manual_buy: ManualBuy,
) -> PipelineStatus | None:
    raw_symbols = ask_stock_ids()

    if raw_symbols is None:
        return None

    stock_ids = parse_stock_ids(raw_symbols)

    if not stock_ids:
        console.print("[yellow]No stock IDs entered.[/yellow]")
        return None

    context = await pipeline.analyse_specific_stocks(stock_ids)

    print_stock_reports(context.manual_stocks)

    await offer_manual_watchlist(
        stocks=context.manual_stocks,
        watch_stocks=watch_stocks,
    )

    await offer_manual_buy(
        stocks=context.manual_stocks,
        manual_buy=manual_buy,
    )

    return context


def ask_stock_ids() -> str | None:
    try:
        return Prompt.ask("Enter stock IDs separated by space or comma")
    except USER_CANCELLED_EXCEPTIONS:
        console.print("\n[yellow]Operation cancelled.[/yellow]")
        return None


async def offer_manual_watchlist(
    stocks: list[Stock],
    watch_stocks: WatchStocks,
) -> None:
    if not stocks:
        return

    confirmed = Confirm.ask(
        "Add these stocks to the manual watchlist?",
        default=False,
    )

    if not confirmed:
        return

    watchlist = await watch_stocks.execute(
        stocks=stocks,
        watchlist_type=WatchlistType.MANUAL,
    )

    print_watchlist_result(watchlist.willing_stocks)


async def offer_manual_buy(
    stocks: list[Stock],
    manual_buy: ManualBuy,
) -> None:
    for stock in stocks:
        confirmed = Confirm.ask(
            f"BUY {stock.stock_id} now using manual override?",
            default=False,
        )

        if not confirmed:
            continue

        result = await manual_buy.execute(stock)

        print_manual_buy_result(result)


def print_watchlist_result(
    stocks: list[Stock],
) -> None:
    if not stocks:
        console.print("[yellow]No stocks were added.[/yellow]")
        return

    stock_ids = ", ".join(stock.stock_id for stock in stocks)

    console.print(f"[green]Added to manual watchlist: {stock_ids}[/green]")


def print_manual_buy_result(
    status: PipelineStatus,
) -> None:
    if status.orders:
        order = status.orders[-1]

        console.print(f"[green]Manual BUY result: {order.stock_id} | {order.status.value.upper()} | Qty={order.quantity}[/green]")
        return

    if status.stats.errors:
        console.print(f"[red]{status.stats.errors[-1]}[/red]")
        return

    if status.signals:
        console.print("[yellow]Manual BUY signal created, but no order was submitted.[/yellow]")


def parse_stock_ids(
    raw_symbols: str,
) -> list[str]:
    normalized_symbols = raw_symbols.replace(",", " ")

    return [symbol.strip() for symbol in normalized_symbols.split() if symbol.strip()]


def print_context_summary(
    context: PipelineStatus,
) -> None:
    console.print("[bold green]Execution Complete[/bold green]")

    console.print(
        f"Scanned={context.stats.total_scanned}, "
        f"Survivors={len(context.survivors)}, "
        f"Signals={context.stats.signals_generated}, "
        f"Orders={context.stats.orders_submitted}, "
        f"Errors={context.stats.total_errors}"
    )

    if not context.signals:
        console.print("No trading signals generated.")
        return

    print_signals_table(context)


def print_signals_table(
    context: PipelineStatus,
) -> None:
    table = Table(title="Signals")

    table.add_column("Stock")
    table.add_column("Action")
    table.add_column("Score", justify="right")
    table.add_column("Qty", justify="right")
    table.add_column("Reason")

    for signal in context.signals:
        table.add_row(
            signal.stock_id,
            signal.action.value.upper(),
            str(signal.score),
            str(signal.quantity),
            signal.reason,
        )

    console.print(table)


def print_stock_reports(
    stocks: list[Stock],
) -> None:
    if not stocks:
        console.print("[yellow]No stocks loaded.[/yellow]")
        return

    table = create_stock_report_table()

    for stock in stocks:
        add_stock_report_row(
            table=table,
            stock=stock,
        )

    console.print(table)


def create_stock_report_table() -> Table:
    table = Table(title="Stock Reports")

    table.add_column("Stock")
    table.add_column("Name")
    table.add_column("Price", justify="right")
    table.add_column("Tech", justify="right")
    table.add_column("AI", justify="right")
    table.add_column("Composite", justify="right")
    table.add_column("Hard Failures")
    table.add_column("Soft Failures")
    table.add_column("Observations")
    table.add_column("AI Summary")

    return table


def add_stock_report_row(
    table: Table,
    stock: Stock,
) -> None:
    ai_summary = stock.ai_report.summary if stock.ai_report else "-"

    table.add_row(
        stock.stock_id,
        stock.name or "",
        format_number(stock.current_price),
        format_optional_int(stock.technical_score),
        format_optional_int(stock.ai_score),
        format_optional_int(stock.composite_score),
        ", ".join(stock.hard_failures) or "-",
        ", ".join(stock.soft_failures) or "-",
        ", ".join(stock.observations) or "-",
        ai_summary,
    )


def format_label(value: str) -> str:
    return value.replace("_", " ").upper()


def format_number(
    value: float | None,
) -> str:
    if value is None:
        return "-"

    return f"{value:.2f}"


def format_optional_int(
    value: int | None,
) -> str:
    if value is None:
        return "-"

    return str(value)


if __name__ == "__main__":
    try:
        if sys.platform == "win32":
            asyncio.run(
                interactive_menu(),
                loop_factory=asyncio.SelectorEventLoop,
            )
        else:
            asyncio.run(interactive_menu())

    except (
        KeyboardInterrupt,
        asyncio.CancelledError,
        SystemExit,
    ):
        pass

    finally:
        os._exit(0)
