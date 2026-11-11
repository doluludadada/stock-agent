"""
`just search-strategies --level tune --seed 1`: one strategy search from a built-in strategy on the held daily history
(Pipeline.search_strategies), then its report: the spans with the TAIEX over each, how the origin and each winner did
on train, validation and the holdout, and where each winner's holdout return sits in the luck baseline. It starts
without a broker login, orders nothing, asks no AI and changes no saved strategy or setting. Loading the history is a
backtest's: the stock listing from the exchanges' OpenAPI, and the held daily history.
"""

import argparse
import asyncio
import os
import sys
from collections.abc import Sequence
from statistics import median

from rich.table import Table

from a_domain.model.trading.backtest import SearchInputs
from a_domain.rules.technical.search import SearchTrial, StrategySearch
from a_domain.types.enums import SearchLevel, SearchSpan
from a_domain.types.errors import BacktestPeriodUnavailable
from b_application.config.app_config import AppConfig
from b_application.config.settings_loader import get_project_root, load_settings
from d_presentation.cli import terminal
from d_presentation.dependencies import STARTUP_REFUSALS, create_process_state, open_runtime


def search_inputs(config: AppConfig, arguments: Sequence[str]) -> SearchInputs:
    parser = argparse.ArgumentParser(prog="just search-strategies", description="Search for a better technical strategy.")
    parser.add_argument("--level", required=True, choices=[level.value for level in SearchLevel])
    parser.add_argument("--seed", type=int, default=1, help="the random seed; the same seed breeds the same candidates")
    parser.add_argument("--strategy", default=config.technical.initial_strategy_id, help="the built-in strategy to start from")
    parser.add_argument("--population", type=int, default=config.strategy_search.population)
    parser.add_argument("--generations", type=int, default=config.strategy_search.generations)
    parser.add_argument("--buy-score", type=int, default=config.analysis.min_combined_score_buy)
    parser.add_argument("--sell-score", type=int, default=config.analysis.max_combined_score_sell)
    chosen = parser.parse_args(arguments)

    return SearchInputs(
        strategy_id=chosen.strategy,
        level=SearchLevel(chosen.level),
        random_seed=chosen.seed,
        population=chosen.population,
        generations=chosen.generations,
        buy_score=chosen.buy_score,
        sell_score=chosen.sell_score,
    )


async def search_strategies(arguments: Sequence[str]) -> int:
    config = load_settings(get_project_root())
    inputs = search_inputs(config, arguments)

    async with open_runtime(config, create_process_state(config), broker_login=False) as runtime:
        search, location = await runtime.signed_out.search_strategies(inputs)

    print_search(search)
    terminal.console.print(f"Saved in {location}")
    return 0


def print_search(search: StrategySearch) -> None:
    inputs, minutes = search.inputs, (search.finished_at - search.started_at).total_seconds() / 60
    terminal.console.print(
        f"Strategy search, level {inputs.level}, seed {inputs.random_seed}, from {inputs.strategy_id} at buy {inputs.buy_score} "
        f"and sell {inputs.sell_score}: {search.tried} candidates tried, {minutes:.1f} minutes in all."
    )
    spans = Table("Span", "First", "Last", "Sessions", "TAIEX", title="Spans, in time order")

    for span, (first, last) in search.spans.items():
        taiex = search.benchmark_returns[span]
        sessions = search.origin.results[span].sessions
        spans.add_row(str(span), str(first), str(last), str(sessions), "-" if taiex is None else f"{taiex:+.1%}")

    terminal.console.print(spans, results_table(search), luck_line(search))


def results_table(search: StrategySearch) -> Table:
    columns = [f"{span} return / drawdown / trades (closed)" for span in SearchSpan]
    table = Table("Candidate", "Buy / sell", *columns, "Beats of the luck sample", title="Results, each span from fresh cash")
    rows: list[tuple[str, SearchTrial, float | None]] = [("origin", search.origin, None)]
    rows += [
        (f"winner {rank}", winner, share)
        for rank, (winner, share) in enumerate(zip(search.winners, search.luck_percentiles, strict=True), 1)
    ]

    for name, trial, share in rows:
        figures = [
            f"{result.return_pct:+.1%} / {result.max_drawdown_pct:.1%} / {result.trades} ({result.closed_trades})"
            for result in (trial.results[span] for span in SearchSpan)
        ]
        scores = f"{trial.candidate.buy_score} / {trial.candidate.sell_score}"
        table.add_row(name, scores, *figures, "-" if share is None else f"{share:.0%}")

    return table


def luck_line(search: StrategySearch) -> str:
    returns = search.luck_returns

    if not returns:
        return "Luck baseline: no candidate tried traded enough on train."

    return (
        f"Luck baseline: {len(returns)} candidates tried that traded enough on train, drawn at random; their holdout returns "
        f"run from {min(returns):+.1%} to {max(returns):+.1%}, median {median(returns):+.1%}."
    )


if __name__ == "__main__":
    exit_code = 1

    try:
        exit_code = asyncio.run(search_strategies(sys.argv[1:]))
    except SystemExit as stop:
        exit_code = stop.code if isinstance(stop.code, int) else 1
    except (*STARTUP_REFUSALS, BacktestPeriodUnavailable) as error:
        terminal.console.print(str(error), style="red", markup=False, highlight=False)
    except Exception:
        terminal.console.print_exception()
    finally:
        # The database's aiosqlite worker thread outlives close() and would hold the interpreter at exit, so the process
        # ends here; anything unexpected is printed above first, since nothing prints after this.
        sys.stdout.flush()
        os._exit(exit_code)
