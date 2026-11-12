"""
`just backfill-history 2017-01-01`: brings what a ranking backtest reads back to a first day on a personal site
(Pipeline.backfill_history): every market's monthly revenue from MOPS's summary of each month, each exchange's daily
history and TWSE's ex-right references. Each part saves what it fetched as it comes, so after a failure or a timeout,
running it again fetches only what is still missing; it ends with exit code 2 while anything is. It starts without a
broker login, orders nothing and asks no AI.
"""

import argparse
import asyncio
import os
import sys
from collections.abc import Sequence
from datetime import date

from b_application.config.settings_loader import get_project_root, load_settings
from d_presentation.cli import terminal
from d_presentation.dependencies import STARTUP_REFUSALS, create_process_state, open_runtime


async def backfill_history(arguments: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(prog="just backfill-history", description="Bring the history a ranking reads back to a day.")
    parser.add_argument("first", type=date.fromisoformat, help="the first day to hold, such as 2017-01-01")
    first: date = parser.parse_args(arguments).first
    config = load_settings(get_project_root())

    async with open_runtime(config, create_process_state(config), broker_login=False) as runtime:
        history, revenue = await runtime.signed_out.backfill_history(first)

    if history is None or revenue is None:
        terminal.console.print("This site reads its history from the open-data archive alone, which nothing backfills.")
        return 1

    held, missing, unread = history
    read, due = revenue
    span = f"from {held[0]} to {held[-1]}" if held else "none"
    terminal.console.print(f"Monthly revenue: {read} of the {due} months due read from MOPS.")
    terminal.console.print(f"Daily history: {len(held)} sessions held, {span}; {len(missing)} index sessions still lack their bars.")

    if missing:
        terminal.console.print(f"Still missing: {', '.join(map(str, missing[:10]))}{' ...' if len(missing) > 10 else ''}")

    for market, start, end in unread:
        terminal.console.print(f"The {market.value.upper()} index from {start} to {end} could not be read yet.")

    return 0 if read == due and not missing and not unread else 2


if __name__ == "__main__":
    exit_code = 1

    try:
        exit_code = asyncio.run(backfill_history(sys.argv[1:]))
    except SystemExit as stop:
        exit_code = stop.code if isinstance(stop.code, int) else 1
    except STARTUP_REFUSALS as error:
        terminal.console.print(str(error), style="red", markup=False, highlight=False)
    except Exception:
        terminal.console.print_exception()
    finally:
        # The database's aiosqlite worker thread outlives close() and would hold the interpreter at exit, so the process
        # ends here; anything unexpected is printed above first, since nothing prints after this.
        sys.stdout.flush()
        os._exit(exit_code)
