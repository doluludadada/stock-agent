from datetime import date, datetime
from typing import Any, ClassVar

from sqlalchemy import BigInteger, Column, Text
from sqlmodel import Field, SQLModel

from a_domain.model.market.company_profile import CompanyProfile
from a_domain.types.enums import MarketType
from c_infrastructure.database.utc_datetime import UtcDateTime


class CompanyProfileDTO(SQLModel, table=True):
    """
    One listed company's profile, shared by every user: the primary key keeps one per stock. `market` is saved as text.
    The columns up to `fetched_at` are the exchange's company basic data (LISTING_COLUMNS), which the open-data archive
    replaces at each run; the others are what a personal site read of MOPS and of the annual report.
    """

    __tablename__: ClassVar[str] = "company_profiles"

    stock_id: str = Field(primary_key=True)
    market: str | None = None
    full_name: str | None = None
    short_name: str | None = None
    english_short_name: str | None = None
    industry_code: str | None = None
    founded_on: date | None = None
    listed_on: date | None = None
    paid_in_capital: float | None = None
    issued_shares: int | None = Field(default=None, sa_column=Column(BigInteger, nullable=True))
    chairman: str | None = None
    general_manager: str | None = None
    address: str | None = None
    website: str | None = None
    reported_on: date | None = None
    fetched_at: datetime | None = Field(default=None, sa_type=UtcDateTime)
    main_business: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    english_name: str | None = None
    main_business_url: str | None = None
    main_business_fetched_at: datetime | None = Field(default=None, sa_type=UtcDateTime)
    annual_report_year: int | None = None
    annual_report_file: str | None = None
    annual_report_checked_at: datetime | None = Field(default=None, sa_type=UtcDateTime)

    LISTING_COLUMNS: ClassVar[tuple[str, ...]] = (
        "market",
        "full_name",
        "short_name",
        "english_short_name",
        "industry_code",
        "founded_on",
        "listed_on",
        "paid_in_capital",
        "issued_shares",
        "chairman",
        "general_manager",
        "address",
        "website",
        "reported_on",
        "fetched_at",
    )

    @classmethod
    def values_of(cls, profile: CompanyProfile) -> dict[str, Any]:
        """The row's columns for `profile`."""
        values = {name: getattr(profile, name) for name in cls.model_fields}
        return values | {"market": profile.market.value if profile.market is not None else None}

    def to_domain(self) -> CompanyProfile:
        values: dict[str, Any] = self.model_dump() | {"market": MarketType(self.market) if self.market is not None else None}
        return CompanyProfile(**values)
