"""
`just backfill-history 2017-01-01`: brings what a ranking backtest reads back to a first day on a personal site
(Pipeline.backfill_history): every market's monthly revenue from MOPS's summary of each month, each exchange's daily
history and their ex-right references. Each part saves what it fetched as it comes, so after a failure or a timeout,
running it again fetches only what is still missing; it ends with exit code 2 while anything is. It starts without a
broker login, orders nothing and asks no AI.
"""

import argparse
import sys
from collections.abc import Sequence
from datetime import date

from b_application.config.settings_loader import get_project_root, load_settings
from d_presentation.cli import terminal
from d_presentation.dependencies import create_process_state, open_runtime


async def backfill_history(arguments: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(prog="just backfill-history", description="Bring the history a ranking reads back to a day.")
    parser.add_argument("first", type=date.fromisoformat, help="the first day to hold, such as 2017-01-01")
    first: date = parser.parse_args(arguments).first
    config = load_settings(get_project_root())

    async with open_runtime(config, create_process_state(config), broker_login=False) as runtime:
        backfill = await runtime.signed_out.backfill_history(first)

    history, revenue, eps = backfill.history, backfill.revenue, backfill.eps

    if history is None or revenue is None or eps is None:
        terminal.console.print("This site reads its history from the open-data archive alone, which nothing backfills.")
        return 1

    held, missing, unread = history.held, history.lacking, history.unread
    read, due = revenue
    span = f"from {held[0]} to {held[-1]}" if held else "none"
    terminal.console.print(f"Monthly revenue: {read} of the {due} months due read from MOPS.")
    terminal.console.print(f"Quarterly EPS: {eps[0]} of the {eps[1]} quarters due held from MOPS.")
    terminal.console.print(f"Daily history: {len(held)} sessions held, {span}; {len(missing)} index sessions still lack their bars.")

    if missing:
        terminal.console.print(f"Still missing: {', '.join(map(str, missing[:10]))}{' ...' if len(missing) > 10 else ''}")

    for market, start, end in unread:
        terminal.console.print(f"{market.value.upper()}'s index or ex-right references from {start} to {end} could not be read yet.")

    return 0 if read == due and eps[0] == eps[1] and not missing and not unread else 2


if __name__ == "__main__":
    terminal.run_to_exit(backfill_history(sys.argv[1:]))
