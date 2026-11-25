from collections.abc import Mapping

import httpx

from a_domain.ports.system.logging_provider import ILoggingProvider


async def fetch_page(
    client: httpx.AsyncClient, logger: ILoggingProvider, url: str, params: Mapping[str, str | int] | None = None
) -> str | None:
    """The text of a news site's or PTT's page or feed, or None, logged, when the site refused or could not be reached."""
    try:
        response = await client.get(url, params=params)
        response.raise_for_status()
    except httpx.HTTPError as error:
        logger.warning(f"Request to {url} failed: {error}")
        return None

    return response.text
