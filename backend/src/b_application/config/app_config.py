from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from a_domain.rules.trading.decision import DecisionRule
from a_domain.rules.trading.entry import EntryRule
from a_domain.rules.trading.exit import ExitRule
from a_domain.rules.trading.order_rule import OrderRule
from a_domain.rules.trading.sizing import SizingRule
from a_domain.types.enums import SystemEnvironment
from b_application.config.ai_config import AiConfig, BehaviorConfig, PromptsConfig, TavilyConfig
from b_application.config.api_config import ApiConfig
from b_application.config.chat_config import DbConfig, LineConfig, NotificationConfig
from b_application.config.collect_config import CollectRulesConfig, FolderConfig, FreshnessConfig, QualityFiltersConfig
from b_application.config.sources_config import SourcesConfig
from b_application.config.trading_config import (
    AnalysisConfig,
    MarketConfig,
    MockTradingConfig,
    ShioajiConfig,
    TradingConfig,
    WatchlistConfig,
)
from b_application.config.valuation_config import ValuationConfig


class AppConfig(BaseSettings):
    """Application and infrastructure configuration."""

    model_config = SettingsConfigDict(env_file=(".env", "../.env"), env_file_encoding="utf-8", extra="ignore", frozen=False)

    project_root: Path
    environment: SystemEnvironment = SystemEnvironment.DEV

    ai: AiConfig = Field(default_factory=AiConfig)
    line: LineConfig = Field(default_factory=LineConfig)
    api: ApiConfig = Field(default_factory=ApiConfig)
    behavior: BehaviorConfig = Field(default_factory=BehaviorConfig)
    db: DbConfig = Field(default_factory=DbConfig)
    folder: FolderConfig = Field(default_factory=FolderConfig)
    tavily: TavilyConfig = Field(default_factory=TavilyConfig)
    analysis: AnalysisConfig = Field(default_factory=AnalysisConfig)
    notifications: NotificationConfig = Field(default_factory=NotificationConfig)
    prompts: PromptsConfig = Field(default_factory=PromptsConfig)
    collect_rules: CollectRulesConfig = Field(default_factory=CollectRulesConfig)
    quality: QualityFiltersConfig = Field(default_factory=QualityFiltersConfig)
    market: MarketConfig = Field(default_factory=MarketConfig)
    freshness: FreshnessConfig = Field(default_factory=FreshnessConfig)
    trading: TradingConfig = Field(default_factory=TradingConfig)
    mock_trading: MockTradingConfig = Field(default_factory=MockTradingConfig)
    shioaji: ShioajiConfig = Field(default_factory=ShioajiConfig)
    watchlist: WatchlistConfig = Field(default_factory=WatchlistConfig)
    valuation: ValuationConfig = Field(default_factory=ValuationConfig)
    sources: SourcesConfig = Field(default_factory=SourcesConfig)

    def decision_rule(self) -> DecisionRule:
        """The trading rules as configured. Signals, AccountRiskCheck and ManualSignal all take theirs from here."""
        sizing_rule = SizingRule(
            risk_per_trade_pct=self.analysis.risk_per_trade_pct,
            stop_loss_pct=self.analysis.stop_loss_pct,
            cost_rule=self.market.cost_rule(),
        )

        return DecisionRule(
            entry_rule=EntryRule(buy_threshold=self.analysis.min_combined_score_buy, sizing_rule=sizing_rule),
            exit_rule=ExitRule(stop_loss_pct=self.analysis.stop_loss_pct, sell_threshold=self.analysis.max_combined_score_sell),
        )

    def order_rule(self) -> OrderRule:
        return OrderRule(
            order_mode=self.trading.order_mode,
            execution_provider=self.trading.execution_provider,
            price_freshness=self.freshness.realtime_rule(),
        )
