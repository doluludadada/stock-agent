"""
`just ranking`: the monthly stock ranking at the latest decision session the held daily history holds
(Pipeline.load_ranking). `just ranking-backtest 2017-07-01 2026-11-11`: the ranking replayed over a period against its
benchmark (Pipeline.run_ranking_backtest), with `--holdings` every decision's stocks too. Both read only the held
history and the archived monthly revenue (`just backfill-history`), start without a broker login, order nothing and
ask no AI.
"""

import argparse
import sys
from collections.abc import Sequence
from datetime import date

from rich.table import Table

from a_domain.rules.trading.ranking import Ranking
from a_domain.rules.trading.ranking_backtest import RankingBacktest
from a_domain.types.errors import BacktestPeriodUnavailable, RankingUnavailable
from b_application.config.settings_loader import get_project_root, load_settings
from d_presentation.cli import terminal
from d_presentation.dependencies import create_process_state, open_runtime


def arguments_of(arguments: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="just ranking", description="The monthly stock ranking and its backtest.")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("latest", help="the ranking at the latest decision session")
    backtest = commands.add_parser("backtest", help="the ranking replayed over a period")
    backtest.add_argument("first", type=date.fromisoformat, help="the first day, such as 2017-07-01")
    backtest.add_argument("last", type=date.fromisoformat, help="the last day, such as 2026-11-11")
    backtest.add_argument("--holdings", action="store_true", help="print every decision's stocks")
    return parser.parse_args(arguments)


async def ranking(arguments: Sequence[str]) -> int:
    chosen = arguments_of(arguments)
    config = load_settings(get_project_root())

    async with open_runtime(config, create_process_state(config), broker_login=False) as runtime:
        if chosen.command == "latest":
            print_ranking(await runtime.signed_out.load_ranking())
            return 0

        backtest = await runtime.signed_out.run_ranking_backtest(chosen.first, chosen.last)

    print_backtest(backtest, holdings=chosen.holdings)
    return 0


def print_ranking(ranking: Ranking) -> None:
    title = f"Ranking at the close of {ranking.decided_on}, revenue of {ranking.revenue_month:%Y-%m}"
    table = Table("#", "Stock", "Name", "Revenue acceleration", "Rank", "Near high", "Rank", "Score", title=title)

    for place, stock in enumerate(ranking.stocks, 1):
        table.add_row(
            str(place),
            stock.stock_id,
            stock.stock_name or "",
            f"{stock.revenue_acceleration:.3f}",
            f"{stock.acceleration_rank:.3f}",
            f"{stock.nearness_to_high:.3f}",
            f"{stock.nearness_rank:.3f}",
            f"{stock.score:.3f}",
        )

    terminal.console.print(table)
    terminal.console.print(f"{ranking.universe} stocks in the universe, {ranking.scored} with both factors.")


def print_backtest(backtest: RankingBacktest, *, holdings: bool) -> None:
    sessions = list(backtest.equity_curve)
    summary = Table(
        "",
        "Ranking",
        backtest.benchmark_id,
        title=f"Ranking backtest from {sessions[0]} to {sessions[-1]}, {len(sessions) - 1} sessions",
    )
    rows = [
        ("Total return", backtest.total_return, backtest.benchmark_total_return),
        ("Annual return", backtest.annual_return, backtest.benchmark_annual_return),
        ("Max drawdown", backtest.max_drawdown, backtest.benchmark_max_drawdown),
    ]

    for label, mine, theirs in rows:
        summary.add_row(label, percent(mine), percent(theirs))

    for year, value in backtest.yearly_returns.items():
        summary.add_row(str(year), percent(value), percent(backtest.benchmark_yearly_returns.get(year)))

    terminal.console.print(summary)
    terminal.console.print(f"Fees and tax: {backtest.costs:.1%} of the value in all. {len(backtest.rankings)} decisions.")

    for ranking in backtest.rankings if holdings else []:
        terminal.console.print(
            f"{ranking.decided_on} ({ranking.revenue_month:%Y-%m}): {' '.join(stock.stock_id for stock in ranking.stocks) or '-'}"
        )


def percent(value: float | None) -> str:
    return "-" if value is None else f"{value:+.1%}"


if __name__ == "__main__":
    terminal.run_to_exit(ranking(sys.argv[1:]), RankingUnavailable, BacktestPeriodUnavailable)
