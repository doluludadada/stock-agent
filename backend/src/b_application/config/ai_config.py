from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from a_domain.types.enums import AiProvider


class AiConfig(BaseSettings):
    """AI provider and behaviour settings."""

    model_config = SettingsConfigDict(env_file=(".env", "../.env"), env_file_encoding="utf-8", extra="ignore")

    active_model: AiProvider = AiProvider.GROQ
    available_models: dict[AiProvider, str] = Field(default_factory=dict)

    openai_api_key: str | None = Field(default=None, validation_alias="OPENAI_API_KEY")
    grok_api_key: str | None = Field(default=None, validation_alias="GROK_API_KEY")
    gemini_api_key: str | None = Field(default=None, validation_alias="GEMINI_API_KEY")
    groq_api_key: str | None = Field(default=None, validation_alias="GROQ_API_KEY")

    connection_timeout: int = Field(default=60, description="Timeout for AI model connections")
    temperature: float = Field(default=0.7, ge=0, le=2)
    """How freely the model words its reply: 0 always picks the likeliest words."""

    system_prompt: str | None = None
    rag_injection_prompt: str | None = None
    article_content_length: int = Field(default=500, ge=100)


class BehaviorConfig(BaseModel):
    """System behaviour and toggles."""

    log_level: str | int = "INFO"
    enable_web_search: bool = False
    enable_x_search: bool = False
    enable_inline_citations: bool = True
    web_search_max_results: int = Field(default=2, ge=1, le=5)
    web_search_triggers: frozenset[str] = frozenset()
    """Words in the user's last message that make the Groq adapter search the web first."""

    web_search_allowed_domains: set[str] | None = None
    web_search_excluded_domains: set[str] | None = None
    x_search_allowed_handles: set[str] | None = None
    x_search_excluded_handles: set[str] | None = None


class TavilyConfig(BaseSettings):
    """Tavily search API settings."""

    model_config = SettingsConfigDict(env_file=(".env", "../.env"), env_file_encoding="utf-8", extra="ignore")

    api_key: str | None = Field(default=None, validation_alias="TAVILY_API_KEY")
    search_depth: str = "basic"
    connection_timeout: int = Field(default=30, gt=0)


class PromptsConfig(BaseModel):
    """AI analysis prompt templates."""

    analysis_report_fundamental: str = ""
    analysis_report_momentum: str = ""
    valuation_explanation: str = ""
    social_sentiment: str = ""


class SentimentConfig(BaseModel):
    """How the Buzz report tallies social sentiment. Report only: sentiment never changes signals or orders."""

    min_confidence: float = Field(default=0.5, ge=0, le=1)
    """A post classified with less confidence than this counts as unclear."""

    min_opinions: int = Field(default=2, ge=1)
    """With fewer bullish, bearish or neutral posts than this, the stock's consensus is unclear."""

    consensus_share: float = Field(default=0.6, gt=0.5, le=1)
    """The share of the opinions one stance needs to be the consensus. Above one half, so only one stance can reach it."""
