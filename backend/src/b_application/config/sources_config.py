import math
from datetime import date
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, JsonValue, NonNegativeInt, field_validator, model_validator

from a_domain.rules.collect.company_background import AnnualReportDueRule, MainBusinessDueRule
from a_domain.types.enums import (
    AnnualReportSection,
    FinancialStatement,
    IndustryFormat,
    InformationSource,
    MarketType,
    TableFormat,
    WorldIndicator,
)

COMPANY_BASICS_ADDRESS: dict[str, JsonValue] = {"without": "no company's main business is read from MOPS", "operator_only": True}


ANNUAL_REPORT_ADDRESS: dict[str, JsonValue] = {"without": "no company's annual report is read", "operator_only": True}


class TwseIndexFields(BaseModel):
    """
    The field names of TWSE's daily index report (MI_INDEX), which names them in Chinese and lists every TWSE index of
    its session: the index's name, its ROC session date, its close, the sign of its change and the change unsigned.
    """

    index: str
    date: str
    close: str
    sign: str
    change: str
    taiex: str
    """The TAIEX's name in the `index` field."""


class CompanyProfileFeed(BaseModel):
    """
    One exchange's company profiles in its OpenAPI: where they are, and the fields of a company's code and industry
    code. The other fields are those CompanyProfile keeps; one a settings file does not name is kept as None.
    """

    url: str
    stock_id: str
    industry: str
    report_date: str = ""
    full_name: str = ""
    short_name: str = ""
    english_short_name: str = ""
    founded_on: str = ""
    listed_on: str = ""
    paid_in_capital: str = ""
    issued_shares: str = ""
    chairman: str = ""
    general_manager: str = ""
    address: str = ""
    website: str = ""


class MaterialInformationFeed(BaseModel):
    """
    One exchange's daily material information in its OpenAPI: where it is, and the fields of an announcement's company,
    ROC date and time, subject, the clause it is filed under, the ROC date of the fact it reports and its text.
    """

    url: str
    stock_id: str
    date: str
    time: str
    subject: str
    clause: str
    fact_date: str
    description: str


class QuarterEpsFeed(BaseModel):
    """
    One exchange's latest-quarter EPS statistics in its OpenAPI: where they are, and the fields of a company's code, the
    ROC year, the quarter and the basic EPS of the year to that quarter's end.
    """

    url: str
    stock_id: str
    year: str
    quarter: str
    eps: str


class ValuationRatioFeed(BaseModel):
    """
    One exchange's daily P/E, dividend yield and P/B report in its OpenAPI: where it is, and the fields of a stock's code,
    the ROC session date and each ratio.
    """

    url: str
    stock_id: str
    date: str
    pe_ratio: str
    dividend_yield: str
    pb_ratio: str


class FinancialSummaryFields(BaseModel):
    """
    The columns of one industry format's balance sheet and income statement that QuarterFinancials reads, each figure
    as every name the format's reports give it (TWSE's and TPEX's sometimes differ), the first one a report holds read.
    A figure the format does not report names none.
    """

    revenue: list[str] = []
    gross_profit: list[str] = []
    operating_income: list[str] = []
    net_income: list[str] = []
    total_assets: list[str] = []
    total_liabilities: list[str] = []
    equity: list[str] = []
    book_value_per_share: list[str] = []


class FinancialReportFeeds(BaseModel):
    """
    The TWSE and TPEX OpenAPI's balance sheets and income statements of the latest quarter: one report per market,
    statement and industry format, each with its own columns. The reports name the fields of the served date, the ROC
    year and quarter, and the company's code and name differently, so each lists every name a report gives it, and a row
    is read under the first one it holds. Every other field is archived as served. `summary` names, per industry
    format, the columns each figure of a quarter's summary is read from.
    """

    urls: dict[MarketType, dict[FinancialStatement, dict[IndustryFormat, str]]]
    served_date: list[str]
    year: list[str]
    quarter: list[str]
    stock_id: list[str]
    company_name: list[str]
    summary: dict[IndustryFormat, FinancialSummaryFields]

    @property
    def identity(self) -> frozenset[str]:
        """Every name of the fields that say which company, period and day a row is of, which are not archived as items."""
        return frozenset([*self.served_date, *self.year, *self.quarter, *self.stock_id, *self.company_name])

    @model_validator(mode="after")
    def every_report_has_an_address_and_every_format_a_summary(self) -> Self:
        for market in MarketType:
            for statement in FinancialStatement:
                if missing := set(IndustryFormat) - set(self.urls.get(market, {}).get(statement, {})):
                    raise ValueError(
                        f"sources.exchange.financial_reports.urls.{market}.{statement} needs {', '.join(sorted(missing))}"
                    )

        if missing := set(IndustryFormat) - set(self.summary):
            raise ValueError(f"sources.exchange.financial_reports.summary needs {', '.join(sorted(missing))}")

        return self


class MonthlyRevenueFeed(BaseModel):
    """
    One exchange's monthly revenue summary in its OpenAPI: where it is, and the fields of its served ROC date, the ROC
    year and month ('11509'), the company's code, name and industry, each revenue figure and the note.
    """

    url: str
    served_date: str
    year_month: str
    stock_id: str
    company_name: str
    industry: str
    revenue: str
    previous_month_revenue: str
    last_year_revenue: str
    month_over_month_percent: str
    year_over_year_percent: str
    cumulative_revenue: str
    last_year_cumulative_revenue: str
    cumulative_year_over_year_percent: str
    note: str


class ExchangeNewsFeed(BaseModel):
    """
    TWSE's own news list in its OpenAPI: where it is, the fields of an item's title, address and ROC date, and how a
    title names a stock.
    """

    url: str
    title: str
    link: str
    date: str
    stock_code_pattern: str
    """A regex whose first group is a stock code a title names, in parentheses alone or after the label of a code."""


class QuoteFields(BaseModel):
    """
    The fields of one exchange's closing quotes of a date: a security's code, its prices, the shares traded and its
    change. TWSE writes the change's sign in a field of its own, as HTML, and X where it compared the close to no
    reference; TPEX signs the change and writes a word where it compared it to none.
    """

    stock_id: str
    open: str
    high: str
    low: str
    close: str
    volume: str
    change: str
    sign: str | None = None


class IndexPriceFields(BaseModel):
    """The fields of an exchange's report of its index's open, high, low and close of each session of a month."""

    date: str
    open: str
    high: str
    low: str
    close: str


class IndexVolumeFields(BaseModel):
    """The fields of an exchange's report of its market's volume and its index's change of each session of a month."""

    date: str
    volume: str
    change: str
    earlier_volume: str | None = None
    """The name the report gave its volume in earlier months, in the same unit: read where the report lacks `volume`."""


class DailyReportFeed(BaseModel):
    """
    One exchange's own reports of a date on its site, the daily history of a personal site: the closing quotes of every
    security of one session, and its index's prices and its market's volume of each session of one month. Each URL is a
    template whose {date} is the date asked, a month's by any day of it, formatted as the site reads it.
    """

    quotes_url: str
    quote_fields: QuoteFields
    index_prices_url: str
    index_price_fields: IndexPriceFields
    index_volume_url: str
    index_volume_fields: IndexVolumeFields
    index_volume_lots: bool
    """Whether the volume report counts board lots (market.board_lot_shares shares each) instead of shares."""


class ExRightReferenceReport(BaseModel):
    """
    One exchange's ex-right and ex-dividend results of a range of dates on its site: where they are, a template of the
    first and the last date, and the fields of a row's ROC date, its stock code and its reference price.
    """

    url: str
    date: str
    stock_id: str
    reference: str
    empty_stat: str | None = None
    """The `stat` of its answer to a range without an ex-day, where that answer has no table. None where it serves an empty table."""


class ExRightReferenceFeed(BaseModel):
    """Each exchange's ex-right and ex-dividend results, and how many calendar months one request asks for."""

    reports: dict[MarketType, ExRightReferenceReport]
    months_per_request: int = Field(ge=1, le=12)


class ExchangeSources(BaseModel):
    """
    The TWSE and TPEX OpenAPI: the listings with each stock's latest official close, the daily index reports, the
    company profiles with each company's industry, and the reports it serves only for their latest day, month or
    quarter: the material information, the EPS statistics, the valuation ratios, the balance sheets and income
    statements, the monthly revenue and TWSE's own news. Apart from them, each exchange's own reports of any date on
    its site (`daily_reports`) and their ex-right references (`ex_right_references`), which an open-data site never
    reads (Audience.open_data_only).
    """

    twse_daily_quotes_url: str
    tpex_daily_quotes_url: str
    twse_index_url: str
    twse_index_fields: TwseIndexFields
    tpex_index_url: str
    company_profiles: dict[MarketType, CompanyProfileFeed]
    industry_names: dict[str, str]
    """The exchanges' industry codes, which both company profiles use, and the industry name of each."""

    industry_max_age_hours: float = Field(gt=0, le=168)
    """A market's company profiles are downloaded again once they are this old."""

    website_scheme: Literal["http", "https"] = "http"
    """
    The scheme a company's website gets when its profile names none ('www.asi.ctci.com'): a site that serves https
    redirects an http address there, and one that serves http alone still opens.
    """

    material_information: dict[MarketType, MaterialInformationFeed]
    quarter_eps: dict[MarketType, QuarterEpsFeed]
    valuation_ratios: dict[MarketType, ValuationRatioFeed]
    financial_reports: FinancialReportFeeds
    monthly_revenue: dict[MarketType, MonthlyRevenueFeed]
    exchange_news: ExchangeNewsFeed
    daily_reports: dict[MarketType, DailyReportFeed]
    ex_right_references: ExRightReferenceFeed

    @model_validator(mode="after")
    def every_feed_serves_both_markets(self) -> Self:
        feeds = {
            "company_profiles": self.company_profiles,
            "material_information": self.material_information,
            "quarter_eps": self.quarter_eps,
            "valuation_ratios": self.valuation_ratios,
            "monthly_revenue": self.monthly_revenue,
            "daily_reports": self.daily_reports,
            "ex_right_references.reports": self.ex_right_references.reports,
        }

        for name, feed in feeds.items():
            if missing := set(MarketType) - set(feed):
                raise ValueError(f"sources.exchange.{name} needs a feed for {', '.join(sorted(missing))}")

        return self


class MopsSources(BaseModel):
    """
    MOPS: the bulk income statements (cumulative EPS) and the monthly revenue summary of any past month. The headers are
    the Chinese column names those pages use. The form fields and market codes are what the income-statement form
    posts, and the ages and intervals say how often MOPS is asked.
    """

    eps_url: str
    eps_form_fields: dict[str, str]
    """The form fields every income-statement request posts, besides the market code, year and season."""

    twse_market_code: str
    tpex_market_code: str
    company_id_header: str
    eps_header_prefix: str
    no_data_marker: str
    monthly_revenue_url: str
    """
    A past month's revenue summary of one market as CSV: a template of the market code, the ROC year and the month. Its
    columns are those of sources.exchange.monthly_revenue.
    """

    revenue_deadline_day: int = Field(ge=1, le=28)
    """Companies file a month's revenue by this day of the month after it."""

    request_interval_seconds: float = Field(ge=0, le=60)
    """
    Every request to MOPS goes one at a time, this far apart, whichever page it asks for. Three requests in ten seconds
    got the address refused on 2026-11-14; at five seconds apart every request was answered.
    """

    company_basics_url: Annotated[str, Field(json_schema_extra=COMPANY_BASICS_ADDRESS)] = ""
    """
    MOPS's company basic information as JSON, one POST per company with its code. Empty, like either address below, no
    main business is read: `without` says so at the start while a file does not set it (settings_notices).
    """

    company_basics_origin: Annotated[str, Field(json_schema_extra=COMPANY_BASICS_ADDRESS)] = ""
    """The Origin and Referer a company basic information request names, as MOPS's own page does."""

    company_basics_page_url: Annotated[str, Field(json_schema_extra=COMPANY_BASICS_ADDRESS)] = ""
    """The page a reader opens to see a company's basic information on MOPS: a template of {stock_id}."""

    company_basics_request_field: str = "companyId"
    """The field of a company basic information request that names the company's code."""

    company_basics_result_field: str = "result"
    company_basics_value_field: str = "value"
    main_business_field: str = "mainBusiness"
    english_name_field: str = "companyEnglishName"
    """
    Where the API's answer holds the company, the fields of it that hold the company's main business and its English
    name, and the field of each that holds its text.
    """

    user_agent: str = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
    )
    """The User-Agent a company basic information request sends: a browser's, with nothing about this installation."""

    company_basics_max_age_days: int = Field(default=90, ge=1, le=3650)
    """A company's basic information is asked for again once the site last asked this many days ago."""

    timeout_seconds: float = Field(gt=0, le=600)
    provisional_page_max_age_hours: float = Field(gt=0, le=168)
    """A page that is not final yet is downloaded again once it is this old."""

    filing_deadlines: dict[int, tuple[int, int]]
    """Each quarter's latest statutory filing deadline across company types, as (month, day)."""

    filing_grace_days: NonNegativeInt = Field(le=90)
    """A quarter's filings are final this many days after its deadline, since a deadline on a holiday moves."""

    @property
    def company_basics_set(self) -> bool:
        """Whether the settings name where MOPS's company basic information is and the page a reader opens."""
        return bool(self.company_basics_url and self.company_basics_origin and self.company_basics_page_url)

    def main_business_due_rule(self) -> MainBusinessDueRule:
        return MainBusinessDueRule(max_age_days=self.company_basics_max_age_days)

    @model_validator(mode="after")
    def every_quarter_has_a_real_deadline(self) -> Self:
        if set(self.filing_deadlines) != {1, 2, 3, 4}:
            raise ValueError("sources.mops.filing_deadlines needs a deadline for each of the quarters 1 to 4")

        for month, day in self.filing_deadlines.values():
            date(2025, month, day)

        return self


class AnnualReportSources(BaseModel):
    """
    The exchange's document site (doc.twse.com.tw), where each company uploads its shareholders'-meeting annual report
    as a PDF: the page that lists a company's reports of one meeting year, the request that answers a file's
    time-stamped address, and how a report's text is read and its sections are found. The site disallows every robot,
    so only a personal site reads it (Audience.annual_reports), one request at a time.
    """

    model_config = ConfigDict(use_attribute_docstrings=True)

    index_url: Annotated[str, Field(json_schema_extra=ANNUAL_REPORT_ADDRESS)] = ""
    """
    The page that lists a company's annual reports of one meeting: a template of {stock_id} and {roc_year}, the ROC
    year of the meeting, one more than the fiscal year. It is also the page a reader opens from a kept section. Empty,
    like either address below, no annual report is read, which the start says (settings_notices).
    """

    file_url: Annotated[str, Field(json_schema_extra=ANNUAL_REPORT_ADDRESS)] = ""
    """Where a POST of file_form_fields with the company's code and a file's name answers the file's address."""

    site_url: Annotated[str, Field(json_schema_extra=ANNUAL_REPORT_ADDRESS)] = ""
    """The site a file's address, which it answers as a path, is read from."""

    file_form_fields: dict[str, str] = Field(default={"step": "9", "kind": "F"}, json_schema_extra={"operator_only": True})
    stock_id_form_field: str = Field(default="co_id", json_schema_extra={"operator_only": True})
    file_form_field: str = Field(default="filename", json_schema_extra={"operator_only": True})
    """The fields of that POST that name the company's code and the file."""

    encoding: str = Field(default="big5", json_schema_extra={"operator_only": True})
    """The encoding of the site's pages."""

    file_pattern: str = Field(
        default=r"[0-9]{{4}}_{stock_id}_[0-9A-Za-z]+F04[^\"' <)]*\.pdf", json_schema_extra={"operator_only": True}
    )
    """A report's file name in the listing page: a template of {stock_id}, a regular expression once filled."""

    link_pattern: str = Field(default=r"/pdf/[^'\" >]+", json_schema_extra={"operator_only": True})
    """The file's time-stamped path in the answer of file_url (a regular expression). It expires, so it is read at once."""

    upload_pattern: str = Field(default=r"(\d{2,3})/(\d{2})/(\d{2})", json_schema_extra={"operator_only": True})
    """The ROC date a listing row says its file was uploaded on: year, month and day."""

    user_agent: str = Field(
        default="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36",
        json_schema_extra={"operator_only": True},
    )
    """The User-Agent every request sends: a browser's, with nothing about this installation."""

    request_interval_seconds: float = Field(default=5, ge=0, le=600, json_schema_extra={"operator_only": True})
    """The least time between two requests to the site: a report takes three."""

    timeout_seconds: float = Field(default=180, gt=0, le=1800, json_schema_extra={"operator_only": True})
    max_bytes: int = Field(default=60_000_000, ge=1, le=1_000_000_000, json_schema_extra={"operator_only": True})
    """A report larger than this is not downloaded: the largest of 2026's samples was 6 MB."""

    read_timeout_seconds: float = Field(default=180, gt=0, le=3600, json_schema_extra={"operator_only": True})
    read_memory_mb: int = Field(default=1024, ge=64, le=65_536, json_schema_extra={"operator_only": True})
    """
    How long the worker process that reads a report's text may take, by the clock while the server waits for it and in
    processor time whoever waits, and the address space it may use where the system enforces a limit (Linux). A 6 MB
    report took 1 second and 127 MB.
    """

    first_month: int = Field(default=6, ge=1, le=12, json_schema_extra={"operator_only": True})
    retry_days: int = Field(default=7, ge=1, le=365, json_schema_extra={"operator_only": True})
    """
    From this month on the site looks for last year's report, and for a company whose report it has not found it looks
    again this many days later (AnnualReportDueRule).
    """

    section_patterns: Annotated[dict[AnnualReportSection, list[str]], Field(json_schema_extra=ANNUAL_REPORT_ADDRESS)] = {}
    """
    What marks each section in a report's text, as regular expressions tried in order: the first one that matches the
    body, past the table of contents, starts the section's window. A section the settings do not name is not kept.
    """

    section_titles: Annotated[dict[AnnualReportSection, str], Field(json_schema_extra=ANNUAL_REPORT_ADDRESS)] = {}
    """Each section's heading in the report's language, which a kept section's title shows."""

    title: Annotated[str, Field(json_schema_extra=ANNUAL_REPORT_ADDRESS)] = ""
    """A kept section's title: a template of {roc_year}, the report's ROC fiscal year, and {section}, its heading."""

    section_lead: int = Field(default=80, ge=0, le=2000, json_schema_extra={"operator_only": True})
    section_length: int = Field(default=2500, ge=200, le=20_000, json_schema_extra={"operator_only": True})
    """The characters kept before a section's mark and from it on. A table reads as wrapped text, so it is kept as text."""

    contents_share: float = Field(default=0.05, ge=0, le=0.5, json_schema_extra={"operator_only": True})
    """The share of a report's text from its start in which a mark is the table of contents' and is passed over."""

    contents_leader_pattern: str = Field(default=r"[.…‧·]{6,}|(?:\. ){4,}", json_schema_extra={"operator_only": True})
    contents_leader_reach: int = Field(default=120, ge=0, le=2000, json_schema_extra={"operator_only": True})
    """
    The leader dots that run from a heading to its page number in the table of contents (a regular expression), and
    how many characters from a mark they are looked for in: a mark followed by them is the table of contents' too.
    """

    min_text_length: int = Field(default=2000, ge=0, le=1_000_000, json_schema_extra={"operator_only": True})
    """A report whose pages hold fewer characters than this holds no text to read, as one of scanned images does."""

    @property
    def addresses_set(self) -> bool:
        """Whether the settings name the site's addresses, what marks a section and how a kept section is titled."""
        return bool(self.index_url and self.file_url and self.site_url and self.section_patterns and self.title)

    def reader_request(self) -> dict[str, JsonValue]:
        """What the worker process that reads a report is asked: how its sections are found and what bounds the process."""
        return {
            "patterns": {section.value: list(patterns) for section, patterns in self.section_patterns.items()},
            "lead": self.section_lead,
            "length": self.section_length,
            "contents_share": self.contents_share,
            "min_text_length": self.min_text_length,
            "leader_pattern": self.contents_leader_pattern,
            "leader_reach": self.contents_leader_reach,
            "memory_mb": self.read_memory_mb,
            "cpu_seconds": math.ceil(self.read_timeout_seconds),
        }

    def due_rule(self) -> AnnualReportDueRule:
        return AnnualReportDueRule(first_month=self.first_month, retry_days=self.retry_days)


class PttSources(BaseModel):
    """The PTT Stock board: where its search lives, the markers its pages use, how much of it is read, and the headers sent."""

    base_url: str
    search_path: str
    push_tag: str
    boo_tag: str
    arrow_tag: str
    ticker_label_pattern: str
    """A regex whose first group is the stock id in a post's ticker line."""

    ticker_parenthesized_pattern: str
    """A regex whose first group is a stock id in full-width or ASCII parentheses."""

    title_ticker_pattern: str
    """A regex whose first group is the stock id in a post's title, used when the body names none."""

    posting_reminder_marker: str
    previous_page_label: str
    timeout_seconds: float = Field(gt=0, le=600)
    max_pages: int = Field(gt=0, le=1000)
    """The most search pages read for one tag."""

    max_body_length: int = Field(gt=0, le=100_000)
    """An article's text, its reactions line included, is cut to this many characters."""

    archive_excerpt_length: int = Field(gt=0, le=100_000)
    """How many characters of each article the buzz archive quotes."""

    user_agent: str
    cookie: str
    """The Cookie header every request sends."""


class NewsSources(BaseModel):
    """The cnyes news API and article pages, the Yahoo Taiwan stock news pages, how long each may take and the User-Agent it gets."""

    cnyes_api_url: str
    cnyes_article_url: str
    yahoo_base_url: str
    yahoo_quote_url: str
    cnyes_timeout_seconds: float = Field(gt=0, le=600)
    yahoo_timeout_seconds: float = Field(gt=0, le=600)
    yahoo_min_headline_length: int = Field(ge=0, le=1000)
    """A Yahoo news link whose headline is shorter than this is not an article."""

    yahoo_short_paragraph_length: int = Field(ge=0, le=1000)
    """Without a caas-body, an article's text is its paragraphs longer than this many characters."""

    cnyes_user_agent: str
    yahoo_user_agent: str


class WorldNewsFeed(BaseModel):
    """One publisher's feed of world news, as RSS 2.0."""

    source: InformationSource
    url: str

    @field_validator("source")
    @classmethod
    def a_world_source(cls, source: InformationSource) -> InformationSource:
        if not source.is_world:
            raise ValueError(f"{source.value} publishes no world news feed")

        return source


class WorldIndicatorFeed(BaseModel):
    """
    One public agency's table of dated rows that holds world indicators: where it is served, in which format, which
    field dates a row and how, and which field holds which indicator.
    """

    model_config = ConfigDict(use_attribute_docstrings=True)

    url: str
    """The table's address. `{year}` in it is the current year in Taipei."""

    format: TableFormat
    date_field: str
    date_format: str
    """How date_field writes a day, as strptime reads it: %Y%m%d for 20261113."""

    fields: dict[str, WorldIndicator]


class WorldSources(BaseModel):
    """
    The world news feeds and the world indicators' tables, how long each may take, how large it may be and the
    User-Agent it gets. A file without them, such as a deployment's older copy, reads none (`without`).
    """

    model_config = ConfigDict(use_attribute_docstrings=True)

    news_feeds: list[WorldNewsFeed] = Field(default_factory=list, json_schema_extra={"without": "no world news is read"})
    """The feeds read, in order. A site reads only those of the sources its audience may read (Audience.world_sources)."""

    indicator_feeds: list[WorldIndicatorFeed] = Field(
        default_factory=list, json_schema_extra={"without": "no world indicator is read"}
    )
    table_days: int = Field(default=14, ge=2, le=366)
    """The days back whose readings of a table are kept at each read."""

    user_agent: str = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
    )
    """A browser's, with nothing of the site or its owner in it."""

    timeout_seconds: float = Field(default=20, gt=0, le=600)
    request_pause_seconds: float = Field(default=2, ge=0, le=600)
    """The least time between two requests the world feed makes, of one read or of two."""

    max_bytes: int = Field(default=2_000_000, ge=1, le=100_000_000)
    """
    The most bytes of a response's body, decompressed, that are read. The body is read as it arrives, and a response
    that passes this is given up there and left out.
    """


class AiSources(BaseModel):
    """The OpenAI-compatible endpoints of Grok, Groq and NVIDIA, and Tavily search."""

    grok_base_url: str
    groq_base_url: str
    nvidia_base_url: str
    tavily_search_url: str


class LineSources(BaseModel):
    """The LINE Messaging API, and how a chat reply is split: the longest message, cut at a sentence ending if it can."""

    push_url: str
    multicast_url: str
    multicast_timeout_seconds: float
    sentence_endings: str
    max_message_length: int


class AttributedProvider(BaseModel):
    """An agency whose open data the app reads, by the name it publishes under, and the names of the datasets it reads."""

    provider: str
    datasets: list[str]


class OpenDataAttribution(BaseModel):
    """
    The credit the Open Government Data License v1 asks of every use, in the form of its annex: each providing agency
    with its datasets, the license's notice, and the license's name and address. A use that does not give it holds no
    license from the start (Article 3, paragraph 2), so a page that shows open data shows this too.
    """

    providers: list[AttributedProvider]
    notice: str
    license: str
    license_url: str


class SourcesConfig(BaseModel):
    """
    Where each outside service lives and the text formats its pages use. The values live only in the `sources`
    section of config/appsetting.yaml, which load_settings passes: nothing here reads a file, so a candidate file is
    validated by itself and never filled in from the file on disk.
    """

    exchange: ExchangeSources
    attribution: OpenDataAttribution
    mops: MopsSources
    annual_reports: AnnualReportSources = Field(default_factory=AnnualReportSources)
    ptt: PttSources
    news: NewsSources
    world: WorldSources = Field(default_factory=WorldSources)
    ai: AiSources
    line: LineSources
