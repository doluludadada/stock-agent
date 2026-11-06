from datetime import date
from typing import Self

from pydantic import BaseModel, NonNegativeInt, model_validator

from a_domain.types.enums import FinancialStatement, IndustryFormat, MarketIndex, MarketType


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
    """One exchange's company profiles in its OpenAPI: where they are, and the fields of a company's code and industry code."""

    url: str
    stock_id: str
    industry: str


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
    def _every_report_has_an_address_and_every_format_a_summary(self) -> Self:
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


class ExchangeSources(BaseModel):
    """
    The TWSE and TPEX OpenAPI: the listings with each stock's latest official close, the daily index reports, the
    company profiles with each company's industry, and the reports it serves only for their latest day, month or
    quarter: the material information, the EPS statistics, the valuation ratios, the balance sheets and income
    statements, the monthly revenue and TWSE's own news. Also the TWSE realtime quotes (MIS).
    """

    twse_daily_quotes_url: str
    tpex_daily_quotes_url: str
    twse_index_url: str
    twse_index_fields: TwseIndexFields
    tpex_index_url: str
    company_profiles: dict[MarketType, CompanyProfileFeed]
    industry_names: dict[str, str]
    """The exchanges' industry codes, which both company profiles use, and the industry name of each."""

    industry_max_age_hours: float
    """A market's company profiles are downloaded again once they are this old."""

    material_information: dict[MarketType, MaterialInformationFeed]
    quarter_eps: dict[MarketType, QuarterEpsFeed]
    valuation_ratios: dict[MarketType, ValuationRatioFeed]
    financial_reports: FinancialReportFeeds
    monthly_revenue: dict[MarketType, MonthlyRevenueFeed]
    exchange_news: ExchangeNewsFeed
    mis_quotes_url: str

    @model_validator(mode="after")
    def _every_feed_serves_both_markets(self) -> Self:
        feeds = {
            "company_profiles": self.company_profiles,
            "material_information": self.material_information,
            "quarter_eps": self.quarter_eps,
            "valuation_ratios": self.valuation_ratios,
            "monthly_revenue": self.monthly_revenue,
        }

        for name, feed in feeds.items():
            if missing := set(MarketType) - set(feed):
                raise ValueError(f"sources.exchange.{name} needs a feed for {', '.join(sorted(missing))}")

        return self


class YahooSources(BaseModel):
    """Yahoo Finance, which serves the daily history: the symbol of each market index."""

    index_symbols: dict[MarketIndex, str]

    @model_validator(mode="after")
    def _every_index_has_a_symbol(self) -> Self:
        if missing := set(MarketIndex) - set(self.index_symbols):
            raise ValueError(f"sources.yahoo.index_symbols needs a symbol for {', '.join(sorted(missing))}")

        return self


class MopsSources(BaseModel):
    """
    MOPS: the bulk income statements (cumulative EPS). The headers are the Chinese column names those pages use. The
    form fields and market codes are what the income-statement form posts, and the ages and intervals say how often
    MOPS is asked.
    """

    eps_url: str
    eps_form_fields: dict[str, str]
    """The form fields every income-statement request posts, besides the market code, year and season."""

    twse_market_code: str
    tpex_market_code: str
    company_id_header: str
    eps_header_prefix: str
    no_data_marker: str
    request_interval_seconds: float
    """A cold load sends ten requests to a shared public service, so they go one at a time, this far apart."""

    timeout_seconds: float
    provisional_page_max_age_hours: float
    """A page that is not final yet is downloaded again once it is this old."""

    filing_deadlines: dict[int, tuple[int, int]]
    """Each quarter's latest statutory filing deadline across company types, as (month, day)."""

    filing_grace_days: NonNegativeInt
    """A quarter's filings are final this many days after its deadline, since a deadline on a holiday moves."""

    @model_validator(mode="after")
    def _every_quarter_has_a_real_deadline(self) -> Self:
        if set(self.filing_deadlines) != {1, 2, 3, 4}:
            raise ValueError("sources.mops.filing_deadlines needs a deadline for each of the quarters 1 to 4")

        for month, day in self.filing_deadlines.values():
            date(2025, month, day)

        return self


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
    timeout_seconds: float
    max_pages: int
    """The most search pages read for one tag."""

    max_body_length: int
    """An article's text, its reactions line included, is cut to this many characters."""

    archive_excerpt_length: int
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
    cnyes_timeout_seconds: float
    yahoo_timeout_seconds: float
    yahoo_min_headline_length: int
    """A Yahoo news link whose headline is shorter than this is not an article."""

    yahoo_short_paragraph_length: int
    """Without a caas-body, an article's text is its paragraphs longer than this many characters."""

    cnyes_user_agent: str
    yahoo_user_agent: str


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
    yahoo: YahooSources
    mops: MopsSources
    ptt: PttSources
    news: NewsSources
    ai: AiSources
    line: LineSources
