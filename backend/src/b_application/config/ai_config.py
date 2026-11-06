from string import Formatter
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from a_domain.types.enums import AiProvider


def placeholders(required: set[str], optional: set[str] | None = None) -> AfterValidator:
    """
    A prompt template the code fills with str.format: it must name every required placeholder and no other than the
    optional ones, and write a literal brace twice. An empty template is unset. Checked at startup and before the
    administrator's save, so a broken template never reaches a run.
    """
    allowed = required | (optional or set())

    def check(template: str | None) -> str | None:
        if not template:
            return template

        try:
            names = {field.split(".")[0].split("[")[0] for _, field, _, _ in Formatter().parse(template) if field is not None}
        except ValueError as error:
            raise ValueError(f"not a valid template ({error}); write a literal brace as {{{{ or }}}}") from error

        if unknown := names - allowed:
            raise ValueError(f"unknown placeholders {sorted(unknown)}; this template may use {sorted(allowed)}")

        if missing := required - names:
            raise ValueError(f"missing placeholders {sorted(missing)}")

        return template

    return AfterValidator(check)


type ReportPrompt = Annotated[str, placeholders({"stock_id", "articles_text"})]


class AiConfig(BaseSettings):
    """AI provider and behaviour settings. The API keys come from the environment, every other value from config/appsetting.yaml."""

    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"), env_file_encoding="utf-8", extra="ignore", use_attribute_docstrings=True
    )

    active_model: AiProvider
    """The site's default: the AI model of every run whose user chose none, LINE chat's and the signed-out pages'."""

    available_models: dict[AiProvider, str]
    user_selectable: list[AiProvider] = Field(default_factory=list)
    """The AI models a user may choose for their own runs on My settings, besides active_model. Empty offers only it."""

    openai_api_key: str | None = Field(default=None, validation_alias="OPENAI_API_KEY")
    grok_api_key: str | None = Field(default=None, validation_alias="GROK_API_KEY")
    gemini_api_key: str | None = Field(default=None, validation_alias="GEMINI_API_KEY")
    groq_api_key: str | None = Field(default=None, validation_alias="GROQ_API_KEY")
    nvidia_api_key: str | None = Field(default=None, validation_alias="NVIDIA_API_KEY")
    anthropic_api_key: str | None = Field(default=None, validation_alias="ANTHROPIC_API_KEY")

    connection_timeout: int = Field(description="Timeout for AI model connections")
    temperature: float = Field(ge=0, le=2)
    """How freely the model words its reply: 0 always picks the likeliest words. Claude refuses this setting."""

    max_output_tokens: int = Field(gt=0)
    """The most tokens a Claude reply may use, its thinking included. The other providers use their own default."""

    @property
    def offered_models(self) -> dict[AiProvider, str]:
        """
        Each AI model a user's runs may use, by provider, with its model id: active_model first, then user_selectable.
        startup_settings refuses a start on which one of them lacks its model id or its key.
        """
        return {provider: self.available_models[provider] for provider in (self.active_model, *self.user_selectable)}

    def model_for(self, choice: AiProvider | None) -> AiProvider:
        """The AI model a user's runs use: their choice while the site offers it, else active_model."""
        if choice is None or choice not in self.offered_models:
            return self.active_model

        return choice

    def missing_keys(self) -> dict[str, str]:
        """
        What each offered provider still needs before the app may start, by the setting that offers it (ai.active_model,
        or ai.user_selectable.<index>): its model id under available_models or its API key's environment variable, by
        name only. Empty when every offered provider has both.
        """
        keys = {
            AiProvider.OPENAI: ("OPENAI_API_KEY", self.openai_api_key),
            AiProvider.GROK: ("GROK_API_KEY", self.grok_api_key),
            AiProvider.GEMINI: ("GEMINI_API_KEY", self.gemini_api_key),
            AiProvider.GROQ: ("GROQ_API_KEY", self.groq_api_key),
            AiProvider.NVIDIA: ("NVIDIA_API_KEY", self.nvidia_api_key),
            AiProvider.CLAUDE: ("ANTHROPIC_API_KEY", self.anthropic_api_key),
        }
        offered = {"ai.active_model": self.active_model} | {
            f"ai.user_selectable.{index}": provider for index, provider in enumerate(self.user_selectable)
        }
        missing = {}

        for path, provider in offered.items():
            name, key = keys[provider]

            if provider not in self.available_models:
                missing[path] = f"{provider.value} needs its model id under ai.available_models.{provider.value}"
            elif not (key and key.strip()):
                missing[path] = f"{provider.value} needs {name} in the environment or .env"

        return missing

    system_prompt: str | None = None
    rag_injection_prompt: Annotated[str | None, placeholders({"search_results"})] = None
    article_content_length: int = Field(ge=100)


class BehaviorConfig(BaseModel):
    """System behaviour and toggles. The web and X search filters default to none; the rest comes from config/appsetting.yaml."""

    log_level: Literal["TRACE", "DEBUG", "INFO", "SUCCESS", "WARNING", "ERROR", "CRITICAL"] | int
    """A loguru level name or number: the logger refuses any other at startup."""
    enable_web_search: bool
    enable_x_search: bool
    enable_inline_citations: bool
    web_search_max_results: int = Field(ge=1, le=5)
    web_search_triggers: frozenset[str]
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

    analysis_report_fundamental: ReportPrompt = ""
    analysis_report_momentum: ReportPrompt = ""
    valuation_explanation: Annotated[
        str,
        placeholders({"valuation_facts", "valuation_rules", "data_warnings"}, {"stock_id", "stock_name", "industry", "articles_text"}),
    ] = ""
    """The domain's numbers, rules and data warnings must reach the AI, which only explains them."""

    social_sentiment: Annotated[str, placeholders({"stock_id", "posts_text"})] = ""


class SentimentConfig(BaseModel):
    """How the Buzz report tallies social sentiment. Report only: sentiment never changes signals or orders."""

    min_confidence: float = Field(default=0.5, ge=0, le=1)
    """A post classified with less confidence than this counts as unclear."""

    min_opinions: int = Field(default=2, ge=1)
    """With fewer bullish, bearish or neutral posts than this, the stock's consensus is unclear."""

    consensus_share: float = Field(default=0.6, gt=0.5, le=1)
    """The share of the opinions one stance needs to be the consensus. Above one half, so only one stance can reach it."""
