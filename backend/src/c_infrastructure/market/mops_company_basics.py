from typing import Any, override

import httpx

from a_domain.ports.market.company_basics_provider import CompanyBasics, ICompanyBasicsProvider
from a_domain.ports.system.logging_provider import ILoggingProvider
from b_application.config.sources_config import MopsSources
from c_infrastructure.market.request_pace import HostPace


class MopsCompanyBasicsProvider(ICompanyBasicsProvider):
    """
    MOPS's company basic information from its JSON API, one POST per company, each after its turn on the pace every
    request to MOPS shares (`pace`, which the wiring keeps in the database). The request names a browser and the MOPS
    site as its origin, as the site's own page does, and nothing about this installation.
    """

    def __init__(self, mops: MopsSources, pace: HostPace, logger: ILoggingProvider) -> None:
        self._mops = mops
        self._pace = pace
        self._logger = logger

    @override
    async def fetch(self, stock_id: str) -> CompanyBasics | None:
        mops = self._mops
        headers = {"User-Agent": mops.user_agent, "Origin": mops.company_basics_origin, "Referer": f"{mops.company_basics_origin}/"}
        await self._pace.wait(mops.request_interval_seconds)

        try:
            async with httpx.AsyncClient(timeout=mops.timeout_seconds, headers=headers) as client:
                response = await client.post(mops.company_basics_url, json={mops.company_basics_request_field: stock_id})
                response.raise_for_status()
                answer = response.json()
        except Exception as error:
            self._logger.warning(f"MOPS company basics {stock_id}: request failed: {type(error).__name__}: {error}")
            return None

        if not isinstance(answer, dict) or mops.company_basics_result_field not in answer:
            self._logger.warning(f"MOPS company basics {stock_id}: unrecognised answer ({len(response.content)} bytes)")
            return None

        result = answer[mops.company_basics_result_field]
        return CompanyBasics(
            main_business=served_value(result, mops.main_business_field, mops.company_basics_value_field),
            english_name=served_value(result, mops.english_name_field, mops.company_basics_value_field),
            url=mops.company_basics_page_url.format(stock_id=stock_id),
        )


def served_value(result: Any, field: str, value_field: str) -> str | None:
    """
    The text of one field of the API's result, each field an object with its text under `value_field`, its white space
    single. None when the result is none, as for a code MOPS holds no company of, or the field is absent or blank.
    """
    held = result.get(field) if isinstance(result, dict) else None
    value = held.get(value_field) if isinstance(held, dict) else None
    text = " ".join(value.split()) if isinstance(value, str) else ""
    return text or None
