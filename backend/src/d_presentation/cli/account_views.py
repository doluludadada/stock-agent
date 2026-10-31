"""Menu 7: the account now, its equity curve and the account as of a date. It never places an order."""

from datetime import date

from rich.table import Table

from a_domain.model.trading.account_valuation import AccountValuation
from a_domain.model.trading.equity_point import EquityPoint
from d_presentation.cli import terminal
from d_presentation.dependencies import Runtime


async def show_account_history(runtime: Runtime) -> None:
    as_of = ask_as_of_date()
    report = await runtime.account_history.execute(as_of=as_of)

    print_account_valuation("Account Now", report.current)
    print_marks_not_live(report.current, report.live_stock_ids)
    print_equity_curve(report.equity_curve)

    if as_of is None:
        return

    if report.as_of is None:
        terminal.console.print(f"[yellow]No fill recorded on or before {as_of.isoformat()}.[/yellow]")
        return

    snapshot, valuation = report.as_of
    print_account_valuation(f"Account As Of {as_of.isoformat()} (last fill {terminal.format_datetime(snapshot.taken_at)})", valuation)


def ask_as_of_date() -> date | None:
    raw_date = terminal.ask_user("Show the account as of date (YYYY-MM-DD, blank to skip)")

    if raw_date is None or not raw_date.strip():
        return None

    try:
        return date.fromisoformat(raw_date.strip())
    except ValueError:
        terminal.console.print(f"[yellow]Not a date: {raw_date}. Showing the current account only.[/yellow]")
        return None


def print_account_valuation(title: str, valuation: AccountValuation) -> None:
    table = Table(title=title)
    table.add_column("Stock")

    for column in ("Qty", "Avg Cost", "Price"):
        table.add_column(column, justify="right")

    table.add_column("Price Time")
    table.add_column("Market Value", justify="right")
    table.add_column("Unrealized PnL", justify="right")

    for held in valuation.positions:
        table.add_row(
            held.position.stock_id,
            str(held.position.quantity),
            terminal.format_number(held.position.average_cost),
            terminal.format_number(held.mark.close if held.mark else None),
            terminal.format_datetime(held.mark.ts if held.mark else None),
            terminal.format_number(held.market_value),
            terminal.format_number(held.unrealized_pnl),
        )

    terminal.console.print(table)
    terminal.console.print(
        f"Cash={terminal.format_number(valuation.cash)}, Market Value={terminal.format_number(valuation.market_value)}, "
        f"Equity={terminal.format_number(valuation.equity)}, Unrealized PnL={terminal.format_number(valuation.unrealized_pnl)}"
    )


def print_marks_not_live(valuation: AccountValuation, live_stock_ids: frozenset[str]) -> None:
    """A position whose live quote did not arrive would otherwise look current in the table."""
    for held in valuation.positions:
        stock_id = held.position.stock_id

        if stock_id in live_stock_ids:
            continue

        if held.mark is None:
            terminal.console.print(
                f"[yellow]Warning: no price for {stock_id}. It is valued at its average cost, with no unrealized PnL.[/yellow]"
            )
            continue

        terminal.console.print(
            f"[yellow]Warning: no live quote for {stock_id}. Its price is the daily close of "
            f"{terminal.format_datetime(held.mark.ts)}, not the current price.[/yellow]"
        )


def print_equity_curve(points: list[EquityPoint]) -> None:
    if not points:
        terminal.console.print("No fills recorded yet, so there is no equity curve.")
        return

    table = Table(title="Equity Curve")
    table.add_column("Day")

    for column in ("Cash", "Market Value", "Equity"):
        table.add_column(column, justify="right")

    for point in points:
        table.add_row(
            point.day.isoformat(),
            terminal.format_number(point.cash),
            terminal.format_number(point.market_value),
            terminal.format_number(point.equity),
        )

    terminal.console.print(table)
