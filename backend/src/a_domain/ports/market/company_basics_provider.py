from typing import Protocol

from pydantic.dataclasses import dataclass

from a_domain.types.values import NonEmptyText


@dataclass(frozen=True, kw_only=True)
class CompanyBasics:
    """What MOPS's company basic information says of one company beyond the exchanges' open data, in the company's own words."""

    main_business: str | None
    """The company's main business as filed, its lines joined. None when MOPS holds no such company or names no business."""

    english_name: str | None
    url: NonEmptyText
    """The page a reader opens to see the company's basic information on MOPS."""


class ICompanyBasicsProvider(Protocol):
    """
    MOPS's company basic information, one request per company. MOPS disallows every robot, so only a site whose
    audience reads MOPS (Audience.mops) has an adapter. Every request to MOPS, this one's and the income statements',
    waits its turn on one pace for the host.
    """

    async def fetch(self, stock_id: str) -> CompanyBasics | None:
        """
        What MOPS says of the company now. None when MOPS could not be asked: the connection was refused or timed out,
        or the answer was no such report. It never raises.
        """
        ...
