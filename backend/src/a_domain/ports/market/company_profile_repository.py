from collections.abc import Sequence
from typing import Protocol

from a_domain.model.market.company_profile import CompanyProfile


class ICompanyProfileRepository(Protocol):
    """
    What the site holds about each listed company itself, one profile per stock, shared by every user and kept across
    restarts. Its parts come from different sources at different times, so each writer names what it read.
    """

    async def find(self, stock_id: str) -> CompanyProfile | None:
        """The stock's profile, or None while no source served one."""
        ...

    async def save_listings(self, profiles: Sequence[CompanyProfile]) -> None:
        """
        Keeps what the exchanges' company profiles served of each company: a new company's profile is added, and one
        already held takes the exchange's fields alone, so its main business and its annual report stay as held.
        Saving the same profiles again changes nothing but when they were fetched.
        """
        ...

    async def save(self, profile: CompanyProfile) -> None:
        """Replaces the stock's profile with `profile`, every part of it."""
        ...
