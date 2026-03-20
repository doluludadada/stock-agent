from pathlib import Path

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from a_domain.types.enums import AiProvider, DatabaseProvider, StrategyName, SystemEnvironment


class AiConfig(BaseSettings):
    """AI provider and behavior settings."""

    model_config = SettingsConfigDict(env_file=(".env", "../.env"), env_file_encoding="utf-8", extra="ignore")

    active_model: AiProvider = AiProvider.GROQ
    available_models: dict[AiProvider, str] = Field(default_factory=dict)
    openai_api_key: str | None = Field(default=None, validation_alias="OPENAI_API_KEY")
    grok_api_key: str | None = Field(default=None, validation_alias="GROK_API_KEY")
    gemini_api_key: str | None = Field(default=None, validation_alias="GEMINI_API_KEY")
    groq_api_key: str | None = Field(default=None, validation_alias="GROQ_API_KEY")
    connection_timeout: int = Field(default=60, description="Timeout for AI model connections")
    system_prompt: str | None = None
    rag_injection_prompt: str | None = None
    article_content_length: int = Field(default=500, ge=100)
    neutral_score: int = Field(default=50, ge=0, le=100)
    ai_response_dir: str = "ai_responses"


class LineConfig(BaseSettings):
    """LINE Bot credentials."""

    model_config = SettingsConfigDict(env_file=(".env", "../.env"), env_file_encoding="utf-8", extra="ignore")

    channel_id: str | None = Field(default=None, validation_alias="LINE_CHANNEL_ID")
    channel_secret: str | None = Field(default=None, validation_alias="LINE_CHANNEL_SECRET")
    channel_access_token: str | None = Field(default=None, validation_alias="LINE_CHANNEL_ACCESS_TOKEN")


class BehaviorConfig(BaseModel):
    """System behavior and toggles."""

    log_level: str | int = "INFO"
    enable_web_search: bool = False
    enable_x_search: bool = False
    enable_inline_citations: bool = True
    web_search_max_results: int = Field(default=2, ge=1, le=5)
    web_search_allowed_domains: set[str] | None = None
    web_search_excluded_domains: set[str] | None = None
    x_search_allowed_handles: set[str] | None = None
    x_search_excluded_handles: set[str] | None = None


class DbConfig(BaseSettings):
    """Database configuration for RAG and Application data."""

    model_config = SettingsConfigDict(env_file=(".env", "../.env"), env_file_encoding="utf-8", extra="ignore")

    provider: DatabaseProvider = DatabaseProvider.MEMORY
    chroma_persist_path: str = "chroma_db"
    reset_commands: set[str] = Field(default={"clear"})
    user: str | None = Field(default=None, validation_alias="DB_USER")
    password: str | None = Field(default=None, validation_alias="DB_PASSWORD")
    host: str | None = Field(default=None, validation_alias="DB_HOST")
    port: int = Field(default=5432, validation_alias="DB_PORT")
    name: str | None = Field(default=None, validation_alias="DB_NAME")


class TavilyConfig(BaseSettings):
    """Tavily search API settings."""

    model_config = SettingsConfigDict(env_file=(".env", "../.env"), env_file_encoding="utf-8", extra="ignore")

    api_key: str | None = Field(default=None, validation_alias="TAVILY_API_KEY")
    search_depth: str = "basic"


class AnalysisConfig(BaseModel):
    """Analysis pipeline weighting and risk parameters."""

    active_strategy: StrategyName = Field(default=StrategyName.MODERATE)
    lookback_days: int = Field(default=120, ge=30)
    technical_weight: float = Field(default=0.6, ge=0.0, le=1.0)
    sentiment_weight: float = Field(default=0.4, ge=0.0, le=1.0)
    min_combined_score_buy: int = Field(default=70, ge=0, le=100)
    max_combined_score_sell: int = Field(default=30, ge=0, le=100)
    risk_per_trade_pct: float = Field(default=0.02, ge=0.01, le=0.1)
    stop_loss_pct: float = Field(default=0.10, ge=0.01, le=0.5)
    total_capital: int = Field(default=1000000, ge=10000)
    article_fetch_limit: int = Field(default=20, ge=1, le=100)


class NotificationConfig(BaseModel):
    """Notification settings."""

    enabled: bool = False
    recipients: list[str] = Field(default_factory=list)


class PromptsConfig(BaseModel):
    """AI analysis prompt templates."""

    analysis_report_fundamental: str = ""
    analysis_report_momentum: str = ""


class CollectRulesConfig(BaseModel):
    """Rules for collecting and filtering data."""

    spam_keywords: set[str] = Field(default={"廣告", "廣編", "業配", "新聞稿"})
    filter_min_price: float = 10.0
    filter_min_volume: int = 500
    buzz_min_mentions: int = 20
    buzz_min_push_count: int = 100
    social_trending_limit: int = Field(default=10, ge=1, le=100)
    news_archive_dir: str = "news_archive"
    ptt_required_tags: set[str] = Field(default={"[標的]"})

    # PTT scraper settings
    ptt_lookback_days: int = Field(default=5, ge=1, le=30)
    ptt_min_push_score: int = Field(default=10, ge=0)
    ptt_tags: list[str] = Field(default=["[標的]", "[新聞]"])


class ScoringConfig(BaseModel):
    """Rules and penalties for scoring."""

    base: int = Field(default=50, ge=0, le=100)
    pass_bonus: int = Field(default=20, ge=0)
    hard_failure_penalty: int = Field(default=15, ge=0)
    max_hard_penalty: int = Field(default=30, ge=0)
    soft_failure_penalty: int = Field(default=5, ge=0)
    max_soft_penalty: int = Field(default=15, ge=0)
    rsi_sweet_spot_bonus: int = Field(default=10, ge=0)
    rsi_sweet_spot_min: float = Field(default=40.0, ge=0.0, le=100.0)
    rsi_sweet_spot_max: float = Field(default=60.0, ge=0.0, le=100.0)
    macd_bullish_bonus: int = Field(default=10, ge=0)
    ma_present_bonus: int = Field(default=5, ge=0)


class QualityFiltersConfig(BaseModel):
    """Minimum text quality requirements."""

    min_chars_stock: int = Field(default=100, ge=0)
    min_chars_news: int = Field(default=200, ge=0)
    min_chars_gossip: int = Field(default=50, ge=0)


class IndicatorConfig(BaseModel):
    """
    Configuration for Technical Indicator parameters.

    TODO (Frontend Integration):
    Currently loaded from appsetting.yaml. In the future, these should be
    exposed to the user via the UI (e.g., Flet Dashboard) allowing them to
    tune periods dynamically without touching configuration files.
    """

    rsi_period: int = 14
    macd_fast: int = 12
    macd_slow: int = 26
    macd_signal: int = 9
    ma_short: int = 5
    ma_mid: int = 20
    ma_long: int = 60
    bb_period: int = 20
    bb_std: float = 2.0
    stoch_k: int = 9
    stoch_d: int = 3
    adx_period: int = 14
    atr_period: int = 14
    mfi_period: int = 14


class StrategyThresholds(BaseModel):
    """Threshold values for one screening strategy, loaded from YAML."""

    # Trend
    rsi_healthy_min: float = 50.0
    rsi_healthy_max: float = 70.0
    rsi_overbought: float = 80.0

    # Safety
    stoch_overbought: float = 80.0
    bollinger_max_pct_b: float = 0.9
    max_daily_volatility: float = 0.07
    min_liquidity: int = 500
    min_price: float = 15.0
    volume_dry_ratio: float = 0.5

    # Volume
    volume_above_avg_ratio: float = 1.0
    volume_breakout_ratio: float = 1.5

    # ADX
    adx_min: float = 20.0
    adx_max: float = 50.0

    # Bollinger
    bollinger_squeeze_bandwidth: float = 0.1

    # ATR
    atr_min_pct: float = 0.01
    atr_max_pct: float = 0.05

    # MFI
    mfi_overbought: float = 80.0

    # Golden Cross
    golden_cross_margin: float = 0.03

    # Entry Timing
    max_drop_pct: float = 0.03
    min_volume_confirmation: float = 0.5
    max_gap_pct: float = 0.03
    max_intraday_range_position: float = 0.8
    max_consecutive_up_days: int = 4


class AppConfig(BaseSettings):
    """
    Application Configuration.

    Load from config.yaml via infrastructure layer.
    """

    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
        frozen=False,
    )

    project_root: Path
    environment: SystemEnvironment = Field(default=SystemEnvironment.DEV)

    ai: AiConfig = Field(default_factory=AiConfig)
    line: LineConfig = Field(default_factory=LineConfig)
    behavior: BehaviorConfig = Field(default_factory=BehaviorConfig)
    db: DbConfig = Field(default_factory=DbConfig)
    tavily: TavilyConfig = Field(default_factory=TavilyConfig)
    analysis: AnalysisConfig = Field(default_factory=AnalysisConfig)
    notifications: NotificationConfig = Field(default_factory=NotificationConfig)
    prompts: PromptsConfig = Field(default_factory=PromptsConfig)
    collect_rules: CollectRulesConfig = Field(default_factory=CollectRulesConfig)
    scoring: ScoringConfig = Field(default_factory=ScoringConfig)
    quality: QualityFiltersConfig = Field(default_factory=QualityFiltersConfig)
    indicators: IndicatorConfig = Field(default_factory=IndicatorConfig)
    strategy: StrategyThresholds = Field(default_factory=StrategyThresholds)
