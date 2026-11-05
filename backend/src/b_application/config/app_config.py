from pathlib import Path
from typing import Self

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from a_domain.rules.system.registration import RegistrationRule
from a_domain.rules.trading.cost import AffordableQuantityRule
from a_domain.rules.trading.decision import DecisionRule, RunDecisionsRule
from a_domain.rules.trading.entry import EntryRule, ManualEntryRule
from a_domain.rules.trading.exit import ExitRule, StopLossRule
from a_domain.rules.trading.order_rule import OrderGateRule, OrderRule
from a_domain.rules.trading.reason import AnalysisSummaryRule, EntryReasonRule, ExitReasonRule
from a_domain.rules.trading.sizing import BuyCostRule, SizingRule
from a_domain.types.enums import DatabaseBackend, ExecutionProvider, SettingsFile, SystemEnvironment
from b_application.config.accounts_config import AccountsConfig
from b_application.config.ai_config import AiConfig, BehaviorConfig, PromptsConfig, SentimentConfig, TavilyConfig
from b_application.config.api_config import ApiConfig
from b_application.config.chat_config import ChatConfig, LineConfig, NotificationConfig
from b_application.config.collect_config import CollectRulesConfig, FolderConfig, FreshnessConfig, QualityFiltersConfig
from b_application.config.market_data_config import MarketDataConfig, MarketHoursConfig
from b_application.config.sources_config import SourcesConfig
from b_application.config.trading_config import (
    AnalysisConfig,
    MarketConfig,
    MockTradingConfig,
    ShioajiConfig,
    TechnicalConfig,
    TradingConfig,
    WatchlistConfig,
)
from b_application.config.valuation_config import ValuationConfig


class DbConfig(BaseSettings):
    """
    Where the app keeps its data: the SQL database of accounts, orders, watchlists and technical settings, and the
    Chroma folder of chat and decision memory. The PostgreSQL credentials come from the environment, the rest from
    the `db` section of config/appsetting.yaml. Only db.backend chooses the database. Earlier versions switched to
    PostgreSQL whenever all four credentials were set, so SQLite with all four set is refused as ambiguous.
    """

    model_config = SettingsConfigDict(env_file=(".env", "../.env"), env_file_encoding="utf-8", extra="ignore")

    backend: DatabaseBackend
    chroma_persist_path: str

    user: str | None = Field(default=None, validation_alias="DB_USER")
    password: str | None = Field(default=None, validation_alias="DB_PASSWORD")
    host: str | None = Field(default=None, validation_alias="DB_HOST")
    port: int = Field(default=5432, validation_alias="DB_PORT")
    name: str | None = Field(default=None, validation_alias="DB_NAME")

    @model_validator(mode="after")
    def check_database_selection(self) -> Self:
        credentials = (self.user, self.password, self.host, self.name)
        complete = all(value and value.strip() for value in credentials)

        if self.backend == DatabaseBackend.POSTGRESQL and not complete:
            raise ValueError("db.backend postgresql needs DB_USER, DB_PASSWORD, DB_HOST and DB_NAME; SQLite is not a fallback")

        if self.backend == DatabaseBackend.SQLITE and complete:
            raise ValueError(
                "db.backend is sqlite, but DB_USER, DB_PASSWORD, DB_HOST and DB_NAME are all set. Choose the database with "
                "db.backend: postgresql to use them, or unset them to keep SQLite"
            )

        return self


class AppConfig(BaseSettings):
    """
    Application and infrastructure configuration. A section with no default here comes only from config/appsetting.yaml:
    load_settings passes it, and tests read it through tests/support/settings.py.
    """

    model_config = SettingsConfigDict(env_file=(".env", "../.env"), env_file_encoding="utf-8", extra="ignore", frozen=False)

    project_root: Path = Field(exclude=True)
    """Set by load_settings, never by a settings file: `exclude` marks a field the loader sets, and the key check refuses it."""

    environment: SystemEnvironment = SystemEnvironment.DEV
    settings_revisions: dict[SettingsFile, str] = Field(default_factory=dict, exclude=True)
    """The revision of each settings file this configuration was loaded from, set by load_settings like project_root."""

    ai: AiConfig
    line: LineConfig = Field(default_factory=LineConfig)
    api: ApiConfig = Field(default_factory=ApiConfig)
    behavior: BehaviorConfig
    db: DbConfig
    chat: ChatConfig
    folder: FolderConfig = Field(default_factory=FolderConfig)
    tavily: TavilyConfig = Field(default_factory=TavilyConfig)
    analysis: AnalysisConfig
    technical: TechnicalConfig
    notifications: NotificationConfig = Field(default_factory=NotificationConfig)
    prompts: PromptsConfig = Field(default_factory=PromptsConfig)
    sentiment: SentimentConfig = Field(default_factory=SentimentConfig)
    collect_rules: CollectRulesConfig
    quality: QualityFiltersConfig = Field(default_factory=QualityFiltersConfig)
    market: MarketConfig
    freshness: FreshnessConfig = Field(default_factory=FreshnessConfig)
    market_hours: MarketHoursConfig = Field(default_factory=MarketHoursConfig)
    market_data: MarketDataConfig = Field(default_factory=MarketDataConfig)
    trading: TradingConfig = Field(default_factory=TradingConfig)
    mock_trading: MockTradingConfig = Field(default_factory=MockTradingConfig)
    shioaji: ShioajiConfig
    watchlist: WatchlistConfig = Field(default_factory=WatchlistConfig)
    valuation: ValuationConfig
    accounts: AccountsConfig
    sources: SourcesConfig

    def sizing_rule(self) -> SizingRule:
        return SizingRule(
            risk_per_trade_pct=self.analysis.risk_per_trade_pct,
            stop_loss_pct=self.analysis.stop_loss_pct,
            lot_size=self.analysis.lot_size,
            limit_price_rule=self.market.limit_price_rule(),
            affordable_quantity_rule=AffordableQuantityRule(cost_rule=self.market.cost_rule()),
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
        entry_rule = EntryRule(
            buy_threshold=self.analysis.min_combined_score_buy,
            sizing_rule=self.sizing_rule(),
            reason_rule=EntryReasonRule(item_limit=self.analysis.reason_item_limit, summary_rule=summary_rule),
        )
        exit_rule = ExitRule(
            sell_threshold=self.analysis.max_combined_score_sell,
            stop_loss_rule=self.stop_loss_rule(),
            reason_rule=self.exit_reason_rule(),
        )

        buy_cost_rule = BuyCostRule(limit_price_rule=self.market.limit_price_rule(), cost_rule=self.market.cost_rule())

        return RunDecisionsRule(decision_rule=DecisionRule(entry_rule=entry_rule, exit_rule=exit_rule), buy_cost_rule=buy_cost_rule)

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

    def registration_rule(self) -> RegistrationRule:
        """The sign-up screen and the registration both ask it, so they never disagree."""
        return RegistrationRule(
            registration_open=self.accounts.registration_open, real_broker=self.trading.execution_provider != ExecutionProvider.MOCK
        )
