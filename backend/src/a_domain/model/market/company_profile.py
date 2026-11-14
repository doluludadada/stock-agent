from datetime import date, datetime

from pydantic import NonNegativeFloat, NonNegativeInt
from pydantic.dataclasses import dataclass

from a_domain.types.enums import MarketType
from a_domain.types.values import NonEmptyText


@dataclass(frozen=True, kw_only=True)
class CompanyProfile:
    """
    What the site holds about one listed company itself, one per stock, each part as its source served it and None
    until that source was read. The exchange's company basic data in its OpenAPI gives the names, the dates, the
    capital, the people, the address and the website, on every site. MOPS's company basic information gives the main
    business and the English name, and the annual report on the exchange's document site is named by its fiscal year
    and file: a personal site alone reads those two.
    """

    stock_id: NonEmptyText
    market: MarketType | None = None
    full_name: str | None = None
    short_name: str | None = None
    english_short_name: str | None = None
    industry_code: str | None = None
    """The exchanges' industry code as served, which sources.exchange.industry_names names."""

    founded_on: date | None = None
    listed_on: date | None = None
    paid_in_capital: NonNegativeFloat | None = None
    """In TWD."""

    issued_shares: NonNegativeInt | None = None
    chairman: str | None = None
    general_manager: str | None = None
    address: str | None = None
    website: str | None = None
    """An http or https address. None when the company gave none or what it gave is no such address."""

    reported_on: date | None = None
    """The day the exchange's report that served the fields above is of."""

    fetched_at: datetime | None = None
    """When the site last read the exchange's report."""

    main_business: str | None = None
    """The company's main business as it filed it with MOPS, in its own words: a third party's text."""

    english_name: str | None = None
    main_business_url: str | None = None
    """The page a reader opens to see MOPS's company basic information."""

    main_business_fetched_at: datetime | None = None
    """When the site last asked MOPS, whether or not MOPS answered with a main business."""

    annual_report_year: int | None = None
    """The fiscal year of the annual report whose sections the article store keeps."""

    annual_report_file: str | None = None
    """The report's file name on the document site, which names the day it was uploaded."""

    annual_report_checked_at: datetime | None = None
    """When the site last looked for the stock's annual report, whether or not it found one it could read."""
