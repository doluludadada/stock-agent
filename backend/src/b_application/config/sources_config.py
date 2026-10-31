from typing import override

from pydantic import BaseModel
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict, YamlConfigSettingsSource


class ExchangeSources(BaseModel):
    """The TWSE and TPEX OpenAPI listings with each stock's latest official close, and the TWSE realtime quotes (MIS)."""

    twse_daily_quotes_url: str
    tpex_daily_quotes_url: str
    mis_quotes_url: str


class MopsSources(BaseModel):
    """
    MOPS: the bulk income statements (cumulative EPS) and the income-statement summaries that carry each company's
    industry. The headers are the Chinese column names those pages and feeds use. The form fields and market codes
    are what the income-statement form posts, and the ages and intervals say how often MOPS is asked.
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
    tpex_industries_url: str
    tpex_industry_company_field: str
    industry_field: str
    request_interval_seconds: float
    """A cold load sends ten requests to a shared public service, so they go one at a time, this far apart."""

    timeout_seconds: float
    provisional_page_max_age_hours: float
    """A page that is not final yet is downloaded again once it is this old."""

    industry_max_age_hours: float


class PttSources(BaseModel):
    """The PTT Stock board: where its search lives and the markers its pages use."""

    base_url: str
    search_path: str
    push_tag: str
    boo_tag: str
    arrow_tag: str
    ticker_label_pattern: str
    """A regex whose first group is the stock id in a post's ticker line."""

    ticker_parenthesized_pattern: str
    """A regex whose first group is a stock id in full-width or ASCII parentheses."""

    posting_reminder_marker: str
    previous_page_label: str


class NewsSources(BaseModel):
    """The cnyes news API and article pages, and the Yahoo Taiwan stock news pages."""

    cnyes_api_url: str
    cnyes_article_url: str
    yahoo_base_url: str
    yahoo_quote_url: str


class AiSources(BaseModel):
    """The OpenAI-compatible endpoints of Grok and Groq, and Tavily search."""

    grok_base_url: str
    groq_base_url: str
    tavily_search_url: str


class LineSources(BaseModel):
    """The LINE Messaging API, and how a chat reply is split: the longest message, cut at a sentence ending if it can."""

    push_url: str
    multicast_url: str
    sentence_endings: str
    max_message_length: int


class SourcesConfig(BaseSettings):
    """
    Where each outside service lives and the text formats its pages use. The values live only in the `sources`
    section of config/appsetting.yaml: load_settings passes that section, and an AppConfig built without it reads the
    same section, found like the .env files from the working folder.
    """

    model_config = SettingsConfigDict(
        yaml_file=("config/appsetting.yaml", "../config/appsetting.yaml"), yaml_config_section="sources", extra="forbid"
    )

    exchange: ExchangeSources
    mops: MopsSources
    ptt: PttSources
    news: NewsSources
    ai: AiSources
    line: LineSources

    @classmethod
    @override
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        return (init_settings, YamlConfigSettingsSource(settings_cls))
