"""
`just backfill-company-background`: reads what a personal site holds about the companies of the monthly ranking, the
best scores first (Pipeline.backfill_company_background): each company's main business from MOPS, one request at a time
at sources.mops.request_interval_seconds, then each company's annual-report sections from the exchange's document
site, three requests a report at sources.annual_reports.request_interval_seconds, each saved as it comes. A rerun after
a stop or a refusal reads only what is still due, and the command ends with exit code 2 while anything is. `--top`
names how many of the ranking's scored stocks it covers; without it, every one. It starts without a broker login,
orders nothing and asks no AI. A public site reads nothing.
"""

import argparse
import sys
from collections.abc import Sequence

from a_domain.types.errors import ListingUnavailableError, RankingUnavailable
from b_application.config.settings_loader import get_project_root, load_settings
from d_presentation.cli import terminal
from d_presentation.dependencies import create_process_state, open_runtime


async def backfill_company_background(arguments: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(prog="just backfill-company-background", description=__doc__)
    parser.add_argument("--top", type=int, default=sys.maxsize, help="how many of the ranking's best scores to cover")
    chosen = parser.parse_args(arguments)
    config = load_settings(get_project_root())

    async with open_runtime(config, create_process_state(config), broker_login=False) as runtime:
        backfill = await runtime.signed_out.backfill_company_background(chosen.top)

    (businesses, businesses_due), (reports, reports_due) = backfill.businesses, backfill.reports
    terminal.console.print(
        f"Company background of {backfill.companies} ranked stocks: {businesses} main businesses read from MOPS, "
        f"{businesses_due} left due; {reports} annual reports read from the document site, {reports_due} companies left due."
    )
    return 2 if businesses_due or reports_due else 0


if __name__ == "__main__":
    terminal.run_to_exit(backfill_company_background(sys.argv[1:]), ListingUnavailableError, RankingUnavailable)
