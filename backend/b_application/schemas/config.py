from __future__ import annotations

from pathlib import Path

from pydantic import Field, computed_field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from src.a_domain.types.enums import AiProvider, DatabaseProvider


class AppConfig(BaseSettings):
    """
    Defines the configuration schema required by the application.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        frozen=True,
    )
    project_root: Path

    # -------------------------- AI Model Configuration -------------------------- #

    active_model: AiProvider = Field(description="The AI model currently in use.")
    available_models: dict[AiProvider, str] = Field(
        default_factory=dict,
        description="Mapping of AI provider to concrete model name/id.",
    )
    openai_api_key: str | None = Field(default=None, description="API key for OpenAI models.")
    grok_api_key: str | None = Field(default=None, description="API key for Grok models.")
    gemini_api_key: str | None = Field(default=None, description="API key for Gemini models.")
    groq_api_key: str | None = Field(default=None, description="API Key for Groq models.")
    ai_model_connection_timeout: int = Field(default=60, description="Timeout in seconds for AI model connections.")
    ai_system_prompt: str | None = Field(default=None, description="The system prompt defining the AI personality.")
    ai_rag_injection_prompt: str | None = Field(
        default=None,
        description="System prompt template for injecting web search context (supports {search_results}).",
    )

    # --------------------- Messaging Platform Configuration --------------------- #

    line_channel_id: str | None = Field(default=None, description="Access token for the LINE Messaging API.")
    line_channel_secret: str | None = Field(
        default=None, description="Secret for LINE Messaging API webhook validation."
    )
    line_channel_access_token: str | None = Field(default=None, description="Access token for the LINE Messaging API.")

    # --------------------------- Application Behavior --------------------------- #

    log_level: str | int = Field(
        default="INFO",
        description="Logging level for the application (e.g., 'DEBUG', 10).",
    )
    enable_web_search: bool = Field(default=False, description="Enable native web search for supported models.")
    enable_x_search: bool = Field(default=False, description="Enable X (Twitter) search. Only for Grok.")
    enable_inline_citations: bool = Field(default=True, description="Request inline citations (e.g. [1]) in responses.")
    web_search_max_results: int = Field(default=2, ge=1, le=5, description="Max sources to retrieve per search.")
    web_search_allowed_domains: set[str] | None = Field(default=None)
    web_search_excluded_domains: set[str] | None = Field(default=None)
    x_search_allowed_handles: set[str] | None = Field(default=None)
    x_search_excluded_handles: set[str] | None = Field(default=None)

    # ---------------------------------------------------------------------------- #
    #                                  DB Setting                                  #
    # ---------------------------------------------------------------------------- #
    database_provider: DatabaseProvider = Field(
        default=DatabaseProvider.MEMORY, description="The persistence layer to use."
    )
    chroma_persist_path: str = Field(default="chroma_db", description="Path to store ChromaDB data locally.")

    reset_commands: set[str] = Field(
        default={"clear"},
        description="List of text commands that trigger a conversation reset.",
    )

    # TODO: Move to somewhere.

    @model_validator(mode="after")
    def _validate_active_model_present(self) -> "AppConfig":
        if self.available_models and self.active_model not in self.available_models:
            raise ValueError(
                f"active_model={self.active_model} is not present in available_models: {list(self.available_models)}"
            )
        return self

    @computed_field
    def active_model_name(self) -> str:
        # Convenience accessor for the concrete model id/name of the active provider.

        try:
            return self.available_models[self.active_model]
        except KeyError as exc:
            raise KeyError(
                f"No model mapping for active_model={self.active_model!s}. Please configure available_models."
            ) from exc

    # =====================
    # Tavily (implementation for web search)
    # =====================
    tavily_api_key: str | None = Field(
        default=None,
        description="Tavily API key for web search.",
    )

    tavily_search_depth: str = Field(
        default="basic",
        description="Tavily search depth: 'basic' or 'advanced'.",
    )

    # ---------------------------------------------------------------------------- #
    #                           Analysis Pipeline Config                           #
    # ---------------------------------------------------------------------------- #

    analysis_lookback_days: int = Field(
        default=120,
        ge=30,
        description="Days of historical data to fetch for analysis.",
    )
    technical_weight: float = Field(
        default=0.6,
        ge=0.0,
        le=1.0,
        description="Weight for technical score in combined calculation (0-1).",
    )
    sentiment_weight: float = Field(
        default=0.4,
        ge=0.0,
        le=1.0,
        description="Weight for sentiment score in combined calculation (0-1).",
    )
    min_combined_score_buy: int = Field(
        default=70,
        ge=0,
        le=100,
        description="Minimum combined score to generate BUY signal.",
    )
    max_combined_score_sell: int = Field(
        default=30,
        ge=0,
        le=100,
        description="Maximum combined score to generate SELL signal.",
    )
    risk_per_trade_pct: float = Field(
        default=0.02,
        ge=0.01,
        le=0.1,
        description="Percentage of capital to risk per trade (e.g., 0.02 = 2%).",
    )
    stop_loss_pct: float = Field(
        default=0.10,
        ge=0.01,
        le=0.5,
        description="Default stop loss percentage (e.g., 0.10 = 10%).",
    )
    execution_window_start: str = Field(
        default="13:00",
        description="Start time for the execution pipeline (Tail-End Strategy).",
    )
    total_capital: int = Field(
        default=1000000,
        ge=10000,
        description="Total trading capital for position sizing.",
    )
    article_fetch_limit: int = Field(
        default=20,
        ge=1,
        le=100,
        description="Max articles to fetch per symbol for sentiment analysis.",
    )
    enable_notifications: bool = Field(
        default=False,
        description="Enable trade signal notifications.",
    )
    notification_recipients: list[str] = Field(
        default_factory=list,
        description="User IDs to receive signal notifications.",
    )
    ai_sentiment_prompt: str | None = Field(
        default=None,
        description="Custom prompt template for sentiment analysis (supports {symbol} and {articles_text}).",
    )

    # --- Collection Rules (No Hard Code!) ---
    # Spam
    collect_spam_keywords: set[str] = Field(
        default={"廣告", "廣編", "業配", "新聞稿"}, description="Keywords to identify spam articles."
    )

    # 流動性過濾
    filter_min_price: float = Field(default=10.0, description="Minimum stock price.")
    filter_min_volume: int = Field(default=500, description="Minimum daily volume (lots).")

    # 熱度過濾
    buzz_min_mentions: int = Field(default=20, description="Minimum mentions to be considered trending.")
    buzz_min_push_count: int = Field(default=100, description="Minimum total push count.")

    # -------------------------- AI Prompts (Loaded from YAML) -------------------------- #

    # Default templates are provided here, but should be overridden by instructions.yaml
    ai_sentiment_prompt_fundamental: str = Field(
        default="""
        Target: {stock_id}
        Task: Analyze long-term growth potential based on provided articles.
        Context: {articles_text}
        Output: JSON with confidence_score (0-100), bullish_factors, bearish_factors.
        """,
        description="Prompt template for Fundamental/Technical analysis.",
    )

    ai_sentiment_prompt_momentum: str = Field(
        default="""
        Target: {stock_id}
        Task: Analyze market sentiment, hype, and pump-and-dump risks.
        Context: {articles_text}
        Output: JSON with confidence_score (0-100), bullish_factors, bearish_factors.
        """,
        description="Prompt template for Momentum/Buzz analysis.",
    )
