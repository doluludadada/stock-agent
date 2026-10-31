from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from a_domain.rules.trading.cost import AffordableQuantityRule
from a_domain.rules.trading.decision import DecisionRule, RunDecisionsRule
from a_domain.rules.trading.entry import EntryRule, ManualEntryRule
from a_domain.rules.trading.exit import ExitRule, StopLossRule
from a_domain.rules.trading.order_rule import OrderGateRule, OrderRule
from a_domain.rules.trading.reason import AnalysisSummaryRule, EntryReasonRule, ExitReasonRule
from a_domain.rules.trading.sizing import BuyCostRule, SizingRule
from a_domain.types.enums import SystemEnvironment
from b_application.config.ai_config import AiConfig, BehaviorConfig, PromptsConfig, SentimentConfig, TavilyConfig
from b_application.config.api_config import ApiConfig
from b_application.config.chat_config import DbConfig, LineConfig, NotificationConfig
from b_application.config.collect_config import CollectRulesConfig, FolderConfig, FreshnessConfig, QualityFiltersConfig
from b_application.config.market_data_config import MarketDataConfig, MarketHoursConfig
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
    sentiment: SentimentConfig = Field(default_factory=SentimentConfig)
    collect_rules: CollectRulesConfig = Field(default_factory=CollectRulesConfig)
    quality: QualityFiltersConfig = Field(default_factory=QualityFiltersConfig)
    market: MarketConfig = Field(default_factory=MarketConfig)
    freshness: FreshnessConfig = Field(default_factory=FreshnessConfig)
    market_hours: MarketHoursConfig = Field(default_factory=MarketHoursConfig)
    market_data: MarketDataConfig = Field(default_factory=MarketDataConfig)
    trading: TradingConfig = Field(default_factory=TradingConfig)
    mock_trading: MockTradingConfig = Field(default_factory=MockTradingConfig)
    shioaji: ShioajiConfig = Field(default_factory=ShioajiConfig)
    watchlist: WatchlistConfig = Field(default_factory=WatchlistConfig)
    valuation: ValuationConfig = Field(default_factory=ValuationConfig)
    sources: SourcesConfig = Field(default_factory=SourcesConfig.from_appsetting)

    def sizing_rule(self) -> SizingRule:
        limit_price_rule = self.market.limit_price_rule()
        cost_rule = self.market.cost_rule()

        return SizingRule(
            risk_per_trade_pct=self.analysis.risk_per_trade_pct,
            stop_loss_pct=self.analysis.stop_loss_pct,
            lot_size=self.analysis.lot_size,
            limit_price_rule=limit_price_rule,
            affordable_quantity_rule=AffordableQuantityRule(cost_rule=cost_rule),
            buy_cost_rule=BuyCostRule(limit_price_rule=limit_price_rule, cost_rule=cost_rule),
        )

    def stop_loss_rule(self) -> StopLossRule:
        """AccountRiskCheck's emergency SELL, and the first check of ExitRule."""
        return StopLossRule(stop_loss_pct=self.analysis.stop_loss_pct, reason_rule=self.exit_reason_rule())

    def exit_reason_rule(self) -> ExitReasonRule:
        summary_rule = AnalysisSummaryRule(item_limit=self.analysis.reason_item_limit)

        return ExitReasonRule(item_limit=self.analysis.reason_item_limit, summary_rule=summary_rule)

    def run_decisions_rule(self) -> RunDecisionsRule:
        """The trading decisions of one run, as configured. Signals takes its rules from here."""
        summary_rule = AnalysisSummaryRule(item_limit=self.analysis.reason_item_limit)
        sizing_rule = self.sizing_rule()
        entry_rule = EntryRule(
            buy_threshold=self.analysis.min_combined_score_buy,
            sizing_rule=sizing_rule,
            reason_rule=EntryReasonRule(item_limit=self.analysis.reason_item_limit, summary_rule=summary_rule),
        )
        exit_rule = ExitRule(
            sell_threshold=self.analysis.max_combined_score_sell,
            stop_loss_rule=self.stop_loss_rule(),
            reason_rule=self.exit_reason_rule(),
        )

        return RunDecisionsRule(
            decision_rule=DecisionRule(entry_rule=entry_rule, exit_rule=exit_rule), buy_cost_rule=sizing_rule.buy_cost_rule
        )

    def manual_entry_rule(self) -> ManualEntryRule:
        """ManualSignal's rule: the confirmed BUY skips the buy threshold, never the sizing."""
        return ManualEntryRule(sizing_rule=self.sizing_rule())

    def order_rule(self) -> OrderRule:
        gate_rule = OrderGateRule(
            order_mode=self.trading.order_mode,
            execution_provider=self.trading.execution_provider,
            price_freshness=self.freshness.realtime_rule(),
        )

        return OrderRule(gate_rule=gate_rule, limit_price_rule=self.market.limit_price_rule())
