from datetime import date
from typing import Self

from pydantic import BaseModel, NonNegativeInt, model_validator

from a_domain.types.enums import MarketIndex


class ExchangeSources(BaseModel):
    """The TWSE and TPEX OpenAPI listings with each stock's latest official close, and the TWSE realtime quotes (MIS)."""

    twse_daily_quotes_url: str
    tpex_daily_quotes_url: str
    mis_quotes_url: str


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
    MOPS: the bulk income statements (cumulative EPS) and the company profiles that carry each company's industry
    code. The headers are the Chinese column names those pages and feeds use. The form fields and market codes are what
    the income-statement form posts, and the ages and intervals say how often MOPS is asked.
    """

    eps_url: str
    eps_form_fields: dict[str, str]
    """The form fields every income-statement request posts, besides the market code, year and season."""

    twse_market_code: str
    tpex_market_code: str
    company_id_header: str
    eps_header_prefix: str
    no_data_marker: str
    twse_industries_url: str
    twse_industry_company_field: str
    twse_industry_field: str
    tpex_industries_url: str
    tpex_industry_company_field: str
    tpex_industry_field: str
    industry_names: dict[str, str]
    """The exchanges' industry codes, which both company profiles use, and the industry name of each."""

    request_interval_seconds: float
    """A cold load sends ten requests to a shared public service, so they go one at a time, this far apart."""

    timeout_seconds: float
    provisional_page_max_age_hours: float
    """A page that is not final yet is downloaded again once it is this old."""

    industry_max_age_hours: float
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


class SourcesConfig(BaseModel):
    """
    Where each outside service lives and the text formats its pages use. The values live only in the `sources`
    section of config/appsetting.yaml, which load_settings passes: nothing here reads a file, so a candidate file is
    validated by itself and never filled in from the file on disk.
    """

    exchange: ExchangeSources
    yahoo: YahooSources
    mops: MopsSources
    ptt: PttSources
    news: NewsSources
    ai: AiSources
    line: LineSources
