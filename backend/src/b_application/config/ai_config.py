from string import Formatter
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from a_domain.ports.system.settings_files import SettingsProblem
from a_domain.types.enums import AiProvider, SettingGroup, SettingUnit


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

    system_model: AiProvider = AiProvider.CLAUDE
    """
    The AI model of the site's own writing, the company cards and daily briefs of the monthly ranking's stocks, by its
    provider under available_models, whatever active_model is: Claude, whose listed model is the cheapest the app
    reads. A start needs its model id and its key, as it needs active_model's, only while the site writes by itself
    (stock_page.system_writing.daily_ai_calls above 0).
    """

    openai_api_key: str | None = Field(default=None, validation_alias="OPENAI_API_KEY")
    grok_api_key: str | None = Field(default=None, validation_alias="GROK_API_KEY")
    gemini_api_key: str | None = Field(default=None, validation_alias="GEMINI_API_KEY")
    groq_api_key: str | None = Field(default=None, validation_alias="GROQ_API_KEY")
    nvidia_api_key: str | None = Field(default=None, validation_alias="NVIDIA_API_KEY")
    anthropic_api_key: str | None = Field(default=None, validation_alias="ANTHROPIC_API_KEY")

    connection_timeout: int = Field(
        description="Timeout for AI model connections",
        gt=0,
        le=600,
        json_schema_extra={"steps": [10, 30, 60, 120, 300], "unit": SettingUnit.SECONDS},
    )
    temperature: float = Field(ge=0, le=2, json_schema_extra={"step": 0.1})
    """How freely the model words its reply: 0 always picks the likeliest words. Claude refuses this setting."""

    max_output_tokens: int = Field(gt=0, le=128_000, json_schema_extra={"steps": [1000, 2000, 4000, 8000, 16000, 32000, 64000]})
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

    def missing_keys(self, system_writing: bool) -> dict[str, SettingsProblem]:
        """
        What each offered provider still needs before the app may start, by the setting that offers it (ai.active_model,
        ai.system_model or ai.user_selectable.<index>): its model id under available_models (ai_model_id_missing) or its API key's
        environment variable (ai_key_missing), by name only. Empty when every offered provider has both. The site's own
        writing's provider is named only while the site writes by itself (`system_writing`) and no other setting
        offers it, so one missing key is one problem and a site that writes nothing by itself needs none for it.
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
        system = {"ai.system_model": self.system_model} if system_writing and self.system_model not in offered.values() else {}

        missing = {}

        for path, provider in (offered | system).items():
            name, key = keys[provider]

            if provider not in self.available_models:
                message = f"{provider.value} needs its model id under ai.available_models.{provider.value}"
                missing[path] = SettingsProblem(
                    message=message, path=path, code="ai_model_id_missing", params={"provider": provider.value}
                )
            elif not (key and key.strip()):
                message = f"{provider.value} needs {name} in the environment or .env"
                params: dict[str, str | int | float] = {"provider": provider.value, "variable": name}
                missing[path] = SettingsProblem(message=message, path=path, code="ai_key_missing", params=params)

        return missing

    system_prompt: str | None = None
    rag_injection_prompt: Annotated[str | None, placeholders({"search_results"})] = None
    article_content_length: int = Field(ge=100, le=20_000, json_schema_extra={"steps": [200, 500, 1000, 2000, 5000]})


class BehaviorConfig(BaseModel):
    """
    System behaviour and toggles. The web search filters default to none; the rest comes from config/appsetting.yaml.
    `retired` names the settings this section once had and no longer reads: a settings file that still sets one starts,
    and the start names it (settings_notices).
    """

    model_config = ConfigDict(json_schema_extra={"retired": ["x_search_allowed_handles", "x_search_excluded_handles"]})

    log_level: Literal["TRACE", "DEBUG", "INFO", "SUCCESS", "WARNING", "ERROR", "CRITICAL"] = Field(
        json_schema_extra={"group": SettingGroup.SITE_ACCESS}
    )
    """One of loguru's level names. A save applies it at once."""
    enable_web_search: bool
    enable_x_search: bool
    enable_inline_citations: bool
    web_search_max_results: int = Field(ge=1, le=5)
    web_search_triggers: frozenset[str]
    """Words in the user's last message that make the Groq adapter search the web first."""

    web_search_allowed_domains: set[str] | None = None
    web_search_excluded_domains: set[str] | None = None


class TavilyConfig(BaseSettings):
    """Tavily search API settings."""

    model_config = SettingsConfigDict(env_file=(".env", "../.env"), env_file_encoding="utf-8", extra="ignore")

    api_key: str | None = Field(default=None, validation_alias="TAVILY_API_KEY")
    search_depth: Literal["basic", "advanced"] = "basic"
    """How deep a Tavily search goes: its API takes these two."""

    connection_timeout: int = Field(
        default=30, gt=0, le=600, json_schema_extra={"steps": [10, 30, 60, 120], "unit": SettingUnit.SECONDS}
    )


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
    stock_brief: Annotated[
        str, placeholders({"facts", "language", "window", "price_change", "sentences"}, {"stock_id", "stock_name"})
    ] = ""
    """The held facts, the window and the reply's language must reach the AI, which only describes them. Empty, no brief is written."""

    company_card: Annotated[str, placeholders({"facts", "language", "sentences"}, {"stock_id", "stock_name"})] = ""
    """
    The held facts about the company and the reply's language must reach the AI, which only describes them. Empty, no
    company card is written, and a stock's brief says what the company is from its listing alone.
    """

    stock_brief_advice_phrases: str = ""
    """
    One word or phrase per line. A sentence the AI wrote for a stock brief that holds one of them, compared without
    case, is dropped: a brief describes and never advises. It is no prompt: the site applies it to the AI's reply.
    """

    stock_brief_rise_query: str = ""
    stock_brief_fall_query: str = ""
    """
    What a stock brief looks for, by meaning, among the stock's kept articles of its window and of the days before it:
    one for a window the close rose over, one for a window it fell over, in the articles' language. They are no
    prompts: no AI reads them. Empty, a brief reads the window's newest articles instead.
    """

    stock_brief_company_query: str = ""
    """What a stock brief looks for among the stock's kept articles to say what the company makes and sells. Empty, none."""

    world_brief: Annotated[str, placeholders({"facts", "language", "sentences"}, {"window"})] = ""
    """
    The held readings and world news and the reply's language must reach the AI, which only describes them. Empty, no
    world brief is written.
    """

    world_brief_query: str = ""
    """
    What a world brief looks for, by meaning, among the kept world news of its window, in the news' language. It is no
    prompt: no AI reads it. Empty, a brief reads the window's newest items instead.
    """

    def advice_phrases(self) -> frozenset[str]:
        return frozenset(line.strip() for line in self.stock_brief_advice_phrases.splitlines() if line.strip())


class SentimentConfig(BaseModel):
    """How the Buzz report tallies social sentiment. Report only: sentiment never changes signals or orders."""

    min_confidence: float = Field(default=0.5, ge=0, le=1, json_schema_extra={"step": 0.05, "unit": SettingUnit.PERCENT})
    """A post classified with less confidence than this counts as unclear."""

    min_opinions: int = Field(default=2, ge=1, le=100, json_schema_extra={"steps": [1, 2, 3, 5, 10]})
    """With fewer bullish, bearish or neutral posts than this, the stock's consensus is unclear."""

    consensus_share: float = Field(
        default=0.6, gt=0.5, le=1, json_schema_extra={"steps": [0.55, 0.6, 0.67, 0.75, 0.9], "unit": SettingUnit.PERCENT}
    )
    """The share of the opinions one stance needs to be the consensus. Above one half, so only one stance can reach it."""
