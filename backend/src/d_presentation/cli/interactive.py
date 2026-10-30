import asyncio
import os
import sys
from datetime import datetime

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.table import Table

from a_domain.model.fundamentals.eps import SOURCE_LABELS, Eps
from a_domain.model.market.stock import Stock
from a_domain.model.valuation.scan import MarketValuation, ScanCriteria, ScanStep, ValuationScan
from a_domain.model.valuation.valuation import (
    LABEL,
    LOW_PE_CAVEAT,
    UNDERVALUATION_FORMULA,
    PeRatio,
    StockValuation,
    TargetPe,
    ValuationExplanation,
)
from a_domain.types.enums import WatchlistType
from b_application.pipeline import Pipeline
from b_application.schemas.config import AppConfig
from b_application.schemas.pipeline_status import PipelineStatus
from b_application.use_cases.trade.manual_buy import ManualBuy
from b_application.use_cases.trade.watch_stocks import WatchStocks
from b_application.valuation_pipeline import ValuationPipeline
from d_presentation.cli.cli_container import build_cli_orchestrator

console = Console()

# TODO:simplify it and catch only KeyboardInterrupt locally
USER_CANCELLED_EXCEPTIONS = (KeyboardInterrupt, EOFError)

VALUATION_MENU_CHOICES = ("5", "6")


async def interactive_menu() -> None:
    runtime = await build_cli_orchestrator()

    try:
        while True:
            print_menu(runtime.config)
            choice = ask_menu_choice()

            if choice is None or choice == "0":
                return

            if choice in VALUATION_MENU_CHOICES:
                await execute_valuation_choice(choice=choice, valuation=runtime.valuation, config=runtime.config)
            else:
                context = await execute_menu_choice(
                    choice=choice, pipeline=runtime.pipeline, watch_stocks=runtime.watch_stocks, manual_buy=runtime.manual_buy
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
        return Prompt.ask("Select an option", choices=["0", "1", "2", "3", "4", "5", "6"])
    except USER_CANCELLED_EXCEPTIONS:
        console.print("\n[yellow]Exiting.[/yellow]")
        return None


async def execute_menu_choice(
    choice: str, pipeline: Pipeline, watch_stocks: WatchStocks, manual_buy: ManualBuy
) -> PipelineStatus | None:
    if choice == "1":
        return await pipeline.run_full_cycle()

    if choice == "2":
        return await run_buzz_scan(pipeline)

    if choice == "3":
        return await run_intraday(pipeline)

    if choice == "4":
        return await run_specific_stock_flow(pipeline=pipeline, watch_stocks=watch_stocks, manual_buy=manual_buy)

    return None


async def run_buzz_scan(pipeline: Pipeline) -> PipelineStatus:
    return await pipeline.run_buzz_scan()


async def run_intraday(pipeline: Pipeline) -> PipelineStatus:
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

    console.print("[5] Value Specific Stocks")
    console.print("    Show TTM EPS from MOPS filings, the official close and the current P/E.")
    console.print("    Ask your target P/E; show three fair-price scenarios and an AI explanation.")
    console.print("    Read-only: never touches the watchlist or orders.")
    console.print("")

    console.print("[6] Scan Undervalued Stocks")
    console.print("    Find stocks priced below EPS x your target P/E.")
    console.print("    Optionally confirm the matches with the active technical strategy.")
    console.print("    Read-only: never touches the watchlist or orders.")
    console.print("\n[0] Exit")


async def run_specific_stock_flow(pipeline: Pipeline, watch_stocks: WatchStocks, manual_buy: ManualBuy) -> PipelineStatus | None:
    raw_symbols = ask_stock_ids()

    if raw_symbols is None:
        return None

    stock_ids = parse_stock_ids(raw_symbols)

    if not stock_ids:
        console.print("[yellow]No stock IDs entered.[/yellow]")
        return None

    context = await pipeline.analyse_specific_stocks(stock_ids)

    print_stock_reports(context.manual_stocks)

    await offer_manual_watchlist(stocks=context.manual_stocks, watch_stocks=watch_stocks)

    await offer_manual_buy(stocks=context.manual_stocks, manual_buy=manual_buy)

    return context


def ask_stock_ids() -> str | None:
    try:
        return Prompt.ask("Enter stock IDs separated by space or comma")
    except USER_CANCELLED_EXCEPTIONS:
        console.print("\n[yellow]Operation cancelled.[/yellow]")
        return None


async def offer_manual_watchlist(stocks: list[Stock], watch_stocks: WatchStocks) -> None:
    if not stocks:
        return

    confirmed = Confirm.ask("Add these stocks to the manual watchlist?", default=False)

    if not confirmed:
        return

    watchlist = await watch_stocks.execute(stocks=stocks, watchlist_type=WatchlistType.MANUAL)

    print_watchlist_result(watchlist.willing_stocks)


async def offer_manual_buy(stocks: list[Stock], manual_buy: ManualBuy) -> None:
    for stock in stocks:
        confirmed = Confirm.ask(f"BUY {stock.stock_id} now using manual override?", default=False)

        if not confirmed:
            continue

        result = await manual_buy.execute(stock)
        print_manual_buy_result(result)


def print_watchlist_result(stocks: list[Stock]) -> None:
    if not stocks:
        console.print("[yellow]No stocks were added.[/yellow]")
        return

    stock_ids = ", ".join(stock.stock_id for stock in stocks)

    console.print(f"[green]Added to manual watchlist: {stock_ids}[/green]")


def print_manual_buy_result(status: PipelineStatus) -> None:
    if status.orders:
        order = status.orders[-1]

        console.print(f"[green]Manual BUY result: {order.stock_id} | {order.status.value.upper()} | Qty={order.quantity}[/green]")
        return

    if status.stats.errors:
        console.print(f"[red]{status.stats.errors[-1]}[/red]")
        return

    if status.signals:
        console.print("[yellow]Manual BUY signal created, but no order was submitted.[/yellow]")


def parse_stock_ids(raw_symbols: str) -> list[str]:
    normalized_symbols = raw_symbols.replace(",", " ")

    return [symbol.strip() for symbol in normalized_symbols.split() if symbol.strip()]


def print_context_summary(context: PipelineStatus) -> None:
    console.print("[bold green]Execution Complete[/bold green]")
    console.print(
        f"Scanned={context.stats.total_scanned}, "
        f"Survivors={len(context.survivors)}, "
        f"Signals={context.stats.signals_generated}, "
        f"Orders={context.stats.orders_submitted}, "
        f"Stale={context.stats.stale_market_data_count}, "
        f"Errors={context.stats.total_errors}"
    )

    if context.stale_stock_ids:
        print_stale_market_data(context)

    if not context.signals:
        console.print("No trading signals generated.")
        return

    print_signals_table(context)


def print_stale_market_data(context: PipelineStatus) -> None:
    table = Table(title="Blocked Stale Market Data")
    table.add_column("Stock")
    table.add_column("Last Data Time")

    for stock_id in sorted(context.stale_stock_ids):
        stock = context.stocks_cache.get(stock_id)
        data_time = stock.latest_market_data_at if stock is not None else None

        table.add_row(stock_id, format_datetime(data_time))

    console.print(table)


def print_signals_table(context: PipelineStatus) -> None:
    table = Table(title="Signals")
    table.add_column("Stock")
    table.add_column("Action")
    table.add_column("Score", justify="right")
    table.add_column("Qty", justify="right")
    table.add_column("Data Time")
    table.add_column("Reason")

    for signal in context.signals:
        stock = context.stocks_cache.get(signal.stock_id)
        data_time = stock.latest_market_data_at if stock is not None else None

        table.add_row(
            signal.stock_id,
            signal.action.value.upper(),
            str(signal.score),
            str(signal.quantity),
            format_datetime(data_time),
            signal.reason,
        )

    console.print(table)


def print_stock_reports(stocks: list[Stock]) -> None:
    if not stocks:
        console.print("[yellow]No stocks loaded.[/yellow]")
        return

    table = create_stock_report_table()

    for stock in stocks:
        add_stock_report_row(table=table, stock=stock)

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


def add_stock_report_row(table: Table, stock: Stock) -> None:
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


async def execute_valuation_choice(choice: str, valuation: ValuationPipeline, config: AppConfig) -> None:
    """Menus 5 and 6 receive only the read-only ValuationPipeline: no order or watchlist write is in scope."""
    try:
        if choice == "5":
            await run_valuation_flow(valuation)

        if choice == "6":
            await run_undervalued_scan(valuation, config.valuation.max_scan_explanations)

    except USER_CANCELLED_EXCEPTIONS:
        console.print("\n[yellow]Valuation cancelled.[/yellow]")


async def run_valuation_flow(valuation: ValuationPipeline) -> None:
    raw_symbols = ask_stock_ids()

    if raw_symbols is None:
        return

    stock_ids = parse_stock_ids(raw_symbols)

    if not stock_ids:
        console.print("[yellow]No stock IDs entered.[/yellow]")
        return

    market = await load_market(valuation)
    valuations = find_valuations(market, stock_ids)

    if not valuations:
        console.print("[yellow]No stocks loaded.[/yellow]")
        return

    print_valuation_facts(valuations, market)

    target_pe = None

    if any(isinstance(item.current_pe, PeRatio) for item in valuations):
        target_pe = ask_target_pe()

        if target_pe is None:
            console.print("[yellow]Target P/E cancelled. No fair price or AI explanation was produced.[/yellow]")
            return

    console.print(f"Asking the AI to explain: {', '.join(item.stock.stock_id for item in valuations)}")

    for item in valuations:
        print_valuation_explanation(await valuation.explain(market.appraise(item, target_pe)))


async def run_undervalued_scan(valuation: ValuationPipeline, max_explanations: int) -> None:
    market = await load_market(valuation)

    if not market.valuations:
        console.print("[yellow]No stocks loaded.[/yellow]")
        return

    print_market_reference(market)
    criteria = ask_scan_criteria()

    if criteria is None:
        console.print("[yellow]Scan cancelled.[/yellow]")
        return

    scan = market.screen(criteria)
    print_valuation_step(scan)

    if not scan.survivors:
        return

    if Confirm.ask(f"Confirm {len(scan.survivors)} matches with the active technical strategy?", default=False):
        console.print("Loading daily history for the matches...")
        scan = await valuation.confirm_technical(scan)
        print_technical_step(scan)

    limit = min(len(scan.survivors), max_explanations)

    if limit and Confirm.ask(f"Explain the top {limit} stocks with AI ({limit} AI calls)?", default=False):
        for report in scan.survivors[:limit]:
            print_valuation_explanation(await valuation.explain(report))


async def load_market(valuation: ValuationPipeline) -> MarketValuation:
    console.print("Loading listed stocks, official closes and EPS filings (TWSE, TPEX, MOPS)...")
    market = await valuation.load_market()

    for warning in market.source_warnings:
        console.print(f"[yellow]{warning}[/yellow]")

    return market


def find_valuations(market: MarketValuation, stock_ids: list[str]) -> list[StockValuation]:
    valuations: list[StockValuation] = []

    for stock_id in dict.fromkeys(stock_ids):
        item = market.find(stock_id)

        if item is None:
            console.print(f"[yellow]Stock not found: {stock_id}[/yellow]")
            continue

        valuations.append(item)

    return valuations


def ask_target_pe() -> TargetPe | None:
    while True:
        raw_value = Prompt.ask("Target P/E (a finite number > 0; blank cancels)", default="", show_default=False)

        if not raw_value.strip():
            return None

        try:
            return TargetPe(float(raw_value))
        except ValueError:
            console.print("[red]目標本益比必須是大於 0 的有限數字[/red]")


def ask_scan_criteria() -> ScanCriteria | None:
    target_pe = ask_target_pe()

    if target_pe is None:
        return None

    while True:
        raw_value = Prompt.ask(
            "Minimum undervaluation % (a finite number >= 0, e.g. 20; blank cancels)", default="", show_default=False
        )

        if not raw_value.strip():
            return None

        try:
            return ScanCriteria(target_pe=target_pe, min_undervaluation=float(raw_value) / 100)
        except ValueError:
            console.print("[red]最低低估幅度必須是大於或等於 0 的有限數字[/red]")


def print_market_reference(market: MarketValuation) -> None:
    median = market.median_pe()
    median_text = f"{median.value:.2f} (over {median.sample_size} stocks with EPS > 0 and a fresh close)" if median else "-"

    console.print(f"Market median P/E for reference: {median_text}")
    console.print(
        f"Last closed session: {market.last_closed_session}. A close is stale once two or more weekday sessions "
        "have closed after it; stale closes are excluded from the scan."
    )


def print_valuation_facts(valuations: list[StockValuation], market: MarketValuation) -> None:
    table = Table(title="Valuation Facts")

    for column in ("Stock", "Name", "Industry", "Close (session)", "EPS", "Current P/E", "Industry median P/E"):
        table.add_column(column)

    for item in valuations:
        stock = item.stock
        industry_median = market.median_pe(stock.industry) if stock.industry else None

        table.add_row(
            stock.stock_id,
            stock.name or "",
            stock.industry or "-",
            item.price_text,
            item.eps.describe(),
            item.pe_text,
            f"{industry_median.value:.2f} ({industry_median.sample_size} stocks)" if industry_median else "-",
        )

    console.print(table)
    print_market_reference(market)

    for item in valuations:
        for warning in item.warnings:
            console.print(f"[yellow]{item.stock.stock_id}: {warning}[/yellow]")


def print_valuation_explanation(explanation: ValuationExplanation) -> None:
    stock = explanation.report.stock
    grid = Table.grid(padding=(0, 2))
    grid.add_column(style="bold", no_wrap=True)
    grid.add_column(overflow="fold")

    for section in explanation.sections():
        grid.add_row(section.title, "\n".join(section.lines))

    console.print(Panel(grid, title=f"{stock.stock_id} {stock.name or ''} · {LABEL}", title_align="left"))


def print_valuation_step(scan: ValuationScan) -> None:
    criteria = scan.criteria
    eliminated = scan.elimination_counts(ScanStep.VALUATION)
    scanned = len(scan.survivors) + sum(eliminated.values())

    console.print(f"Valuation step: target P/E {criteria.target_pe.value:.2f}, undervaluation >= {criteria.min_undervaluation:.1%}")
    console.print(f"({UNDERVALUATION_FORMULA})")
    console.print(f"Scanned {scanned} -> passed {len(scan.survivors)}")
    console.print(
        "Eliminated at valuation: " + (" | ".join(f"{reason.label} {count}" for reason, count in eliminated.items()) or "none")
    )

    table = Table(title=f"Undervalued at target P/E {criteria.target_pe.value:.2f} · {LABEL} · not a BUY signal")

    for column in ("#", "Stock", "Name", "Close (session)", "EPS", "Current P/E", "Target P/E", "Fair price", "Undervalued"):
        table.add_column(column)

    table.add_column("EPS period")
    table.add_column("Source")

    for index, report in enumerate(scan.survivors, 1):
        stock = report.stock
        eps = stock.eps
        base = report.base

        table.add_row(
            str(index),
            stock.stock_id,
            stock.name or "",
            report.valuation.price_text,
            f"{eps.value:.2f}" if isinstance(eps, Eps) else "-",
            report.valuation.pe_text,
            f"{base.target_pe:.2f}" if base else "-",
            f"{base.fair_price:,.2f}" if base else "-",
            f"{base.undervaluation:.1%}" if base else "-",
            f"{eps.kind.label} {eps.period_label}" if isinstance(eps, Eps) else "-",
            SOURCE_LABELS[eps.source] if isinstance(eps, Eps) else "-",
        )

    console.print(table)
    console.print(LOW_PE_CAVEAT)


def print_technical_step(scan: ValuationScan) -> None:
    technical_eliminations = scan.technical_eliminations
    table = Table(title=f"Two-step screen: valuation -> technical ({scan.technical_strategy_id})")

    for column in ("Stock", "Name", "Undervalued", "Valuation", "Technical", "Tech score", "Eliminated at", "Reason"):
        table.add_column(column)

    for report in scan.valuation_survivors:
        stock = report.stock
        elimination = technical_eliminations.get(stock.stock_id)

        table.add_row(
            stock.stock_id,
            stock.name or "",
            f"{report.undervaluation:.1%}" if report.undervaluation is not None else "-",
            "passed",
            "eliminated" if elimination else "passed",
            format_optional_int(stock.technical_score),
            elimination.reason.step.label if elimination else "-",
            (elimination.detail or elimination.reason.label) if elimination else "passed both steps",
        )

    console.print(table)

    eliminated = scan.elimination_counts(ScanStep.TECHNICAL)
    console.print(
        f"Passed both steps: {len(scan.survivors)}. Eliminated at technical: "
        + (" | ".join(f"{reason.label} {count}" for reason, count in eliminated.items()) or "none")
    )
    console.print("No trading signal, watchlist entry or order is created. A low P/E is not a BUY signal.")


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

    return value.isoformat(timespec="seconds")


if __name__ == "__main__":
    try:
        if sys.platform == "win32":
            asyncio.run(interactive_menu(), loop_factory=asyncio.SelectorEventLoop)
        else:
            asyncio.run(interactive_menu())

    except KeyboardInterrupt, asyncio.CancelledError, SystemExit:
        pass

    finally:
        os._exit(0)
