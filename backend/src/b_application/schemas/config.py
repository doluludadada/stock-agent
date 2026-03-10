from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from a_domain.types.enums import AiProvider, DatabaseProvider, SystemEnvironment


class AppConfig(BaseSettings):
    """
    Application configuration schema.
    NOTE: This is a candidate for splitting into sub-configs
    (AiConfig, TradingConfig, AnalysisConfig, etc.) in a future refactor.
    """

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore", frozen=True,
    )
    project_root: Path
    environment: SystemEnvironment = Field(default=SystemEnvironment.DEV)

    # AI
    active_model: AiProvider = AiProvider.GROQ
    available_models: dict[AiProvider, str] = Field(default_factory=dict)
    openai_api_key: str | None = None
    grok_api_key: str | None = None
    gemini_api_key: str | None = None
    groq_api_key: str | None = None
    ai_model_connection_timeout: int = 60
    ai_system_prompt: str | None = None
    ai_rag_injection_prompt: str | None = None
    ai_article_content_length: int = Field(default=500, ge=100)

    # LINE
    line_channel_id: str | None = None
    line_channel_secret: str | None = None
    line_channel_access_token: str | None = None

    # Behavior
    log_level: str | int = "INFO"
    enable_web_search: bool = False
    enable_x_search: bool = False
    enable_inline_citations: bool = True
    web_search_max_results: int = Field(default=2, ge=1, le=5)
    web_search_allowed_domains: set[str] | None = None
    web_search_excluded_domains: set[str] | None = None
    x_search_allowed_handles: set[str] | None = None
    x_search_excluded_handles: set[str] | None = None

    # DB
    database_provider: DatabaseProvider = DatabaseProvider.MEMORY
    chroma_persist_path: str = "chroma_db"
    reset_commands: set[str] = Field(default={"clear"})

    # Tavily
    tavily_api_key: str | None = None
    tavily_search_depth: str = "basic"

    # Analysis Pipeline
    analysis_lookback_days: int = Field(default=120, ge=30)
    technical_weight: float = Field(default=0.6, ge=0.0, le=1.0)
    sentiment_weight: float = Field(default=0.4, ge=0.0, le=1.0)
    min_combined_score_buy: int = Field(default=70, ge=0, le=100)
    max_combined_score_sell: int = Field(default=30, ge=0, le=100)
    risk_per_trade_pct: float = Field(default=0.02, ge=0.01, le=0.1)
    stop_loss_pct: float = Field(default=0.10, ge=0.01, le=0.5)
    total_capital: int = Field(default=1000000, ge=10000)
    article_fetch_limit: int = Field(default=20, ge=1, le=100)
    ai_neutral_score: int = Field(default=50, ge=0, le=100)
    enable_notifications: bool = False
    notification_recipients: list[str] = Field(default_factory=list)

    # Prompts
    ai_analysis_report_prompt_fundamental: str = ""
    ai_analysis_report_prompt_momentum: str = ""

    # Collect rules config
    collect_spam_keywords: set[str] = Field(default={"廣告", "廣編", "業配", "新聞稿"})
    filter_min_price: float = 10.0
    filter_min_volume: int = 500
    buzz_min_mentions: int = 20
    buzz_min_push_count: int = 100
    social_trending_limit: int = Field(default=10, ge=1, le=100)

    # Scoring
    score_base: int = Field(default=50, ge=0, le=100)
    score_pass_bonus: int = Field(default=20, ge=0)
    score_hard_failure_penalty: int = Field(default=15, ge=0)
    score_max_hard_penalty: int = Field(default=30, ge=0)
    score_soft_failure_penalty: int = Field(default=5, ge=0)
    score_max_soft_penalty: int = Field(default=15, ge=0)
    score_rsi_sweet_spot_bonus: int = Field(default=10, ge=0)
    score_rsi_sweet_spot_min: float = Field(default=40.0, ge=0.0, le=100.0)
    score_rsi_sweet_spot_max: float = Field(default=60.0, ge=0.0, le=100.0)
    score_macd_bullish_bonus: int = Field(default=10, ge=0)
    score_ma_present_bonus: int = Field(default=5, ge=0)

    # Quality filters
    quality_min_chars_stock: int = Field(default=100, ge=0)
    quality_min_chars_news: int = Field(default=200, ge=0)
    quality_min_chars_gossip: int = Field(default=50, ge=0)


class StrategyThresholds(BaseModel):
    """Threshold values for one screening strategy, loaded from YAML."""

    model_config = ConfigDict(frozen=True)

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
