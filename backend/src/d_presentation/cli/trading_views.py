"""Menus 1 to 4: the trading workflows, the manual watchlist and manual BUY prompts, and the run summary the menu prints."""

from rich.console import JustifyMethod
from rich.table import Table

from a_domain.model.market.stock import Stock
from a_domain.model.trading.watchlist_addition import WatchlistAddition
from a_domain.types.enums import WatchlistType
from b_application.pipeline import Pipeline
from b_application.schemas.pipeline_status import PipelineStatus
from b_application.use_cases.trade.watch_stocks import WatchStocks
from d_presentation.cli import terminal
from d_presentation.dependencies import Runtime

STOCK_REPORT_COLUMNS: tuple[tuple[str, JustifyMethod], ...] = (
    ("Stock", "left"),
    ("Name", "left"),
    ("Price", "right"),
    ("Data Time", "left"),
    ("Tech", "right"),
    ("AI", "right"),
    ("Composite", "right"),
    ("Hard Failures", "left"),
    ("Soft Failures", "left"),
    ("Observations", "left"),
    ("AI Summary", "left"),
)


async def scan_social_buzz(runtime: Runtime) -> PipelineStatus:
    status = await runtime.pipeline.run_buzz_scan()

    print_buzz_report(status)

    return status


async def analyse_specific_stocks(runtime: Runtime) -> PipelineStatus | None:
    stock_ids = terminal.ask_stock_ids()

    if stock_ids is None:
        return None

    status = await runtime.pipeline.analyse_specific_stocks(stock_ids)

    print_stock_reports(status.manual_stocks)

    await offer_manual_watchlist(stocks=status.manual_stocks, watch_stocks=runtime.watch_stocks)

    await offer_manual_buy(stocks=status.manual_stocks, pipeline=runtime.pipeline)

    return status


async def offer_manual_watchlist(stocks: list[Stock], watch_stocks: WatchStocks) -> None:
    if not stocks or not terminal.confirm("Add these stocks to the manual watchlist?"):
        return

    print_watchlist_result(await watch_stocks.execute(stocks=stocks, watchlist_type=WatchlistType.MANUAL))


async def offer_manual_buy(stocks: list[Stock], pipeline: Pipeline) -> None:
    for stock in stocks:
        if terminal.confirm(f"BUY {stock.stock_id} now using manual override?"):
            print_manual_buy_result(stock.stock_id, await pipeline.buy_manually(stock))


def print_watchlist_result(addition: WatchlistAddition) -> None:
    if addition.added_stock_ids:
        terminal.console.print(f"[green]Added to manual watchlist: {', '.join(addition.added_stock_ids)}[/green]")

    if addition.already_present_stock_ids:
        terminal.console.print(
            f"[yellow]Already present on manual watchlist: {', '.join(addition.already_present_stock_ids)}[/yellow]"
        )


def print_manual_buy_result(stock_id: str, status: PipelineStatus) -> None:
    if status.manual_buy_refusal is not None:
        terminal.console.print(f"[yellow]Manual BUY not placed: {stock_id} | {status.manual_buy_refusal}[/yellow]")
        return

    result = status.require_manual_buy_order()
    style = "green" if result.filled_quantity else "red"
    terminal.console.print(
        f"[{style}]Manual BUY result: {result.stock_id} | {result.status.value.upper()} | "
        f"Filled {result.filled_quantity}/{result.quantity} @ {terminal.format_number(result.average_filled_price)} | "
        f"Fee={result.fee} | Reason: {result.reason or '-'}[/{style}]"
    )


def print_buzz_report(status: PipelineStatus) -> None:
    terminal.console.print(f"Buzz Filter: Discussed={status.stats.buzz_scanned}, Qualified={status.stats.buzz_qualified}")

    if not status.buzz_stocks:
        return

    table = Table(title="Social Sentiment", caption="Report only. Sentiment never changes signals or orders.")
    table.add_column("Stock")
    table.add_column("Name")

    for column in ("Posts", "Bullish", "Bearish", "Neutral", "Unclear"):
        table.add_column(column, justify="right")

    table.add_column("Sentiment")

    for stock in status.buzz_stocks:
        table.add_row(stock.stock_id, stock.name or "", *sentiment_cells(status, stock.stock_id))

    terminal.console.print(table)


def sentiment_cells(status: PipelineStatus, stock_id: str) -> tuple[str, ...]:
    sentiment = status.sentiment_by_stock_id.get(stock_id)

    if sentiment is None:
        return ("-", "-", "-", "-", "-", "FAILED")

    return (
        f"{sentiment.classified}/{sentiment.posts}",
        f"{sentiment.bullish_ratio:.0%}",
        f"{sentiment.bearish_ratio:.0%}",
        f"{sentiment.neutral_ratio:.0%}",
        str(sentiment.unclear),
        terminal.format_label(sentiment.consensus.value),
    )


def print_context_summary(status: PipelineStatus) -> None:
    terminal.console.print("[bold green]Execution Complete[/bold green]")
    terminal.console.print(
        f"Scanned={status.stats.total_scanned}, "
        f"Survivors={len(status.survivors)}, "
        f"Signals={status.stats.signals_generated}, "
        f"Orders={status.stats.orders_submitted}, "
        f"Stale={status.stats.stale_market_data_count}, "
        f"Errors={status.stats.total_errors}"
    )

    if status.stale_stock_ids:
        print_stale_market_data(status)

    if not status.signals:
        terminal.console.print("No trading signals generated.")
        return

    print_signals_table(status)

    if status.orders:
        print_orders_table(status)


def print_stale_market_data(status: PipelineStatus) -> None:
    table = Table(title="Blocked Stale Market Data")
    table.add_column("Stock")
    table.add_column("Last Data Time")

    for stock_id in sorted(status.stale_stock_ids):
        stock = status.stocks_cache.get(stock_id)
        data_time = stock.latest_market_data_at if stock is not None else None

        table.add_row(stock_id, terminal.format_datetime(data_time))

    terminal.console.print(table)


def print_signals_table(status: PipelineStatus) -> None:
    table = Table(title="Signals")
    table.add_column("Stock")
    table.add_column("Action")
    table.add_column("Score", justify="right")
    table.add_column("Qty", justify="right")
    table.add_column("Data Time")
    table.add_column("Reason")

    for signal in status.signals:
        table.add_row(
            signal.stock_id,
            signal.action.value.upper(),
            str(signal.score),
            str(signal.quantity),
            terminal.format_datetime(signal.price_observed_at),
            signal.reason,
        )

    terminal.console.print(table)


def print_orders_table(status: PipelineStatus) -> None:
    table = Table(title="Orders")

    for column in ("Stock", "Action", "Status"):
        table.add_column(column)

    for column in ("Filled", "Price", "Fee", "Tax", "Realized PnL"):
        table.add_column(column, justify="right")

    table.add_column("Reason")

    for order in status.orders:
        table.add_row(
            order.stock_id,
            order.action.value.upper(),
            order.status.value.upper(),
            f"{order.filled_quantity}/{order.quantity}",
            terminal.format_number(order.average_filled_price or order.limit_price),
            str(order.fee),
            str(order.tax),
            terminal.format_number(order.realized_pnl),
            order.reason or "-",
        )

    terminal.console.print(table)


def print_stock_reports(stocks: list[Stock]) -> None:
    if not stocks:
        terminal.console.print("[yellow]No stocks loaded.[/yellow]")
        return

    table = Table(title="Stock Reports")

    for column, justify in STOCK_REPORT_COLUMNS:
        table.add_column(column, justify=justify)

    for stock in stocks:
        table.add_row(
            stock.stock_id,
            stock.name or "",
            terminal.format_number(stock.current_price),
            terminal.format_datetime(stock.latest_market_data_at),
            terminal.format_optional_int(stock.technical_score),
            terminal.format_optional_int(stock.ai_score),
            terminal.format_optional_int(stock.composite_score),
            ", ".join(stock.hard_failures) or "-",
            ", ".join(stock.soft_failures) or "-",
            ", ".join(stock.observations) or "-",
            (stock.ai_report.summary if stock.ai_report else "") or "-",
        )

    terminal.console.print(table)
