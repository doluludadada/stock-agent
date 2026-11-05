from datetime import date

from pydantic.dataclasses import dataclass


@dataclass(frozen=True, kw_only=True)
class PostListing:
    """A social post as a board's listing shows it, before its page is read."""

    title: str
    url: str
    posted_on: date
