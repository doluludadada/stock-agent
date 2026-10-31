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
    industry. The headers are the Chinese column names those pages and feeds use.
    """

    eps_url: str
    company_id_header: str
    eps_header_prefix: str
    no_data_marker: str
    twse_industries_url: str
    twse_industry_company_field: str
    tpex_industries_url: str
    tpex_industry_company_field: str
    industry_field: str


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
    """The LINE Messaging API, and the sentence endings a long chat reply is split at."""

    push_url: str
    multicast_url: str
    sentence_endings: str


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
