from typing import Protocol

from pydantic import Field
from pydantic.dataclasses import dataclass

from a_domain.model.market.article import Article


@dataclass(frozen=True, kw_only=True)
class AnnualReport:
    """What the document site holds of one company's annual report of one fiscal year, as the site read it."""

    fiscal_year: int
    file: str | None
    """The report's file name on the document site. None when the site lists no annual report of that year."""

    sections: list[Article] = Field(default_factory=list)
    """
    Each section the report's text holds, as an article of source ANNUAL_REPORT: its title names the fiscal year and
    the section, its address is the page that lists the report, since the file's own address expires, it is published
    on the day the report was uploaded and its fact date is the fiscal year's last day. Empty when no report is listed
    and when the file holds no text to read, as scanned images do.
    """

    readable: bool = True
    """
    False when the listed file could not be read: it is larger than the size limit, no PDF the reader opens, or its
    reading ran out of time or memory. The site looks for the company's report again later, and goes on to the next.
    """


class IAnnualReportProvider(Protocol):
    """
    The companies' shareholders'-meeting annual reports on the exchange's document site. The site disallows every
    robot, so only a site whose audience reads it (Audience.annual_reports) has an adapter, and its requests leave one
    at a time. A report's text is read off the event loop, in a process of its own that ends with it.
    """

    async def fetch(self, stock_id: str, fiscal_year: int) -> AnnualReport | None:
        """
        The company's annual report of that fiscal year as the site lists it now, with its sections; a listed file
        it could not read is answered as not readable. None when the site could not be asked or did not serve the
        file: a refused or timed-out connection, an answer that names no file. It never raises.
        """
        ...
