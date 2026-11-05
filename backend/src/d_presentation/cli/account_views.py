"""Menu 7: the account now, its equity curve and the account as of a date. It never places an order."""

from datetime import date

from rich.table import Table

from a_domain.model.trading.account import Account
from b_application.pipeline import Pipeline
from d_presentation.cli import terminal


async def show_account_history(pipeline: Pipeline) -> None:
    as_of = ask_as_of_date()
    status = await pipeline.load_account_history(as_of)

    print_account_value("Account Now", status.account)
    print_marks_not_live(status.account, status.live_stock_ids)
    print_equity_curve(status.equity_curve)

    if as_of is None:
        return

    if (snapshot := status.account_as_of) is None:
        terminal.console.print(f"[yellow]No fill recorded on or before {as_of.isoformat()}.[/yellow]")
        return

    title = f"Account As Of {as_of.isoformat()} (last fill {terminal.format_datetime(snapshot.taken_at)})"
    print_account_value(title, snapshot.account)


def ask_as_of_date() -> date | None:
    raw_date = terminal.ask_user("Show the account as of date (YYYY-MM-DD, blank to skip)")

    if raw_date is None or not raw_date.strip():
        return None

    try:
        return date.fromisoformat(raw_date.strip())
    except ValueError:
        terminal.console.print(f"[yellow]Not a date: {raw_date}. Showing the current account only.[/yellow]")
        return None


def print_account_value(title: str, value: Account) -> None:
    table = Table(title=title)
    table.add_column("Stock")

    for column in ("Qty", "Avg Cost", "Price"):
        table.add_column(column, justify="right")

    table.add_column("Price Time")
    table.add_column("Market Value", justify="right")
    table.add_column("Unrealized PnL", justify="right")

    for held in value.positions:
        table.add_row(
            held.stock_id,
            str(held.quantity),
            terminal.format_number(held.average_cost),
            terminal.format_number(held.mark_price if held.marked_at else None),
            terminal.format_datetime(held.marked_at),
            terminal.format_number(held.market_value),
            terminal.format_number(held.unrealized_pnl),
        )

    terminal.console.print(table)
    terminal.console.print(
        f"Cash={terminal.format_number(value.cash)}, Market Value={terminal.format_number(value.market_value)}, "
        f"Equity={terminal.format_number(value.equity)}, Unrealized PnL={terminal.format_number(value.unrealized_pnl)}"
    )


def print_marks_not_live(value: Account, live_stock_ids: frozenset[str]) -> None:
    """A position whose live quote did not arrive would otherwise look current in the table."""
    for held in value.positions:
        stock_id = held.stock_id

        if stock_id in live_stock_ids:
            continue

        if held.marked_at is None:
            terminal.console.print(
                f"[yellow]Warning: no price for {stock_id}. It is valued at its average cost, with no unrealized PnL.[/yellow]"
            )
            continue

        terminal.console.print(
            f"[yellow]Warning: no live quote for {stock_id}. Its price is the daily close of "
            f"{terminal.format_datetime(held.marked_at)}, not the current price.[/yellow]"
        )


def print_equity_curve(curve: dict[date, Account]) -> None:
    if not curve:
        terminal.console.print("No fills recorded yet, so there is no equity curve.")
        return

    table = Table(title="Equity Curve")
    table.add_column("Day")

    for column in ("Cash", "Market Value", "Equity"):
        table.add_column(column, justify="right")

    for day, value in curve.items():
        table.add_row(
            day.isoformat(),
            terminal.format_number(value.cash),
            terminal.format_number(value.market_value),
            terminal.format_number(value.equity),
        )

    terminal.console.print(table)
