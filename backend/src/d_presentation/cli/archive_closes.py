"""
`just archive-closes`: saves the official closes, material information, EPS statistics, valuation ratios, balance sheets,
income statements, monthly revenue and TWSE news the TWSE and TPEX OpenAPI serve now into the archive once, as the Web
API does at its start and on its timer, then prints every date, quarter and month the archive holds.
"""

import asyncio
import os

from rich.table import Table

from a_domain.types.errors import ListingUnavailableError
from b_application.config.settings_loader import get_project_root, startup_settings
from d_presentation.cli import terminal
from d_presentation.dependencies import STARTUP_REFUSALS, create_process_state, open_runtime


async def archive_closes() -> int:
    config = startup_settings(get_project_root())

    async with open_runtime(config, create_process_state(config)) as runtime:
        sessions, quarters, months = await runtime.signed_out.archive_daily_closes()

    columns = ("Date", "Stocks", "Indexes", "Valuation ratios", "Material information", "TWSE news")
    table = Table(*columns, title=f"The archive holds {len(sessions)} dates")

    for held in sessions:
        counts = (held.stocks, held.indexes, held.valuation_ratios, held.material_information, held.exchange_news)
        table.add_row(held.session_date.isoformat(), *map(str, counts))

    filed = Table("Quarter", "EPS", "Balance sheets", "Income statements", title=f"The archive holds {len(quarters)} quarters")

    for quarter in quarters:
        filed.add_row(str(quarter.quarter), *map(str, (quarter.eps, quarter.balance_sheets, quarter.income_statements)))

    revenue = Table("Month", "Companies", title=f"The archive holds the revenue of {len(months)} months")

    for month in months:
        revenue.add_row(f"{month.year}-{month.month:02d}", str(month.companies))

    terminal.console.print(table, filed, revenue)
    return 0


if __name__ == "__main__":
    exit_code = 1

    try:
        exit_code = asyncio.run(archive_closes())
    except (*STARTUP_REFUSALS, ListingUnavailableError) as error:
        terminal.console.print(str(error), style="red", markup=False, highlight=False)
    finally:
        os._exit(exit_code)
