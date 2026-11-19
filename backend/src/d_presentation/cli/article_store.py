"""
`just backfill-articles`: keeps the announcements and TWSE news the open-data archive holds in the article store, then
brings the vectors of every stock the store keeps up to date (Pipeline.backfill_article_store). The first run fetches
the text embedding model's files once; a later run embeds only what is new, and after the vectors were lost it computes
them again from the kept articles. It starts without a broker login, reaches no news site, orders nothing and asks no AI.
"""

from a_domain.types.errors import ListingUnavailableError
from b_application.config.settings_loader import get_project_root, load_settings
from d_presentation.cli import terminal
from d_presentation.dependencies import create_process_state, open_runtime


async def backfill_articles() -> int:
    config = load_settings(get_project_root())

    async with open_runtime(config, create_process_state(config), broker_login=False) as runtime:
        backfill = await runtime.signed_out.backfill_article_store()

    terminal.console.print(
        f"The article store took {backfill.kept} new or changed articles from the archive and keeps articles of "
        f"{backfill.stocks} stocks; {backfill.embedded} articles were embedded."
    )
    return 0


if __name__ == "__main__":
    terminal.run_to_exit(backfill_articles(), ListingUnavailableError)
