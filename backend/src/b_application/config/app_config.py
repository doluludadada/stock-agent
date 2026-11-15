from dataclasses import replace
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from a_domain.model.trading.ranking_formula import RankingFormula
from a_domain.rules.ai.company_card import CompanyCardContextRule
from a_domain.rules.ai.stock_brief import BriefReplyRule
from a_domain.rules.ai.world_brief import WorldBriefDueRule
from a_domain.rules.system.registration import RegistrationRule
from a_domain.rules.trading.backtest import BacktestRule, OpenFillRule, SessionStopLossRule
from a_domain.rules.trading.cost import AffordableQuantityRule
from a_domain.rules.trading.decision import DecisionRule, RunDecisionsRule
from a_domain.rules.trading.entry import EntryRule, ManualEntryRule
from a_domain.rules.trading.exit import ExitRule, StopLossRule
from a_domain.rules.trading.follow import FollowScheduleRule, FollowTimeRule, RankingFollowRule
from a_domain.rules.trading.order_rule import (
    BrokerAccessRule,
    BrokerLoginRule,
    BuyLimitRule,
    OrderGateRule,
    OrderPriceRule,
    OrderRule,
    RealBrokerOrdererRule,
)
from a_domain.rules.trading.ranking import DecisionSessionsRule, MonthlyRankingRule
from a_domain.rules.trading.ranking_backtest import RankingBacktestRule, RankingPortfolioRule
from a_domain.rules.trading.reason import AnalysisSummaryRule, EntryReasonRule, ExitReasonRule
from a_domain.rules.trading.sizing import BuyCostRule, SizingRule
from a_domain.types.enums import Audience, BriefKind, Feature, Permission, SettingGroup, SettingsFile, SystemEnvironment
from b_application.config.accounts_config import AccountsConfig
from b_application.config.ai_config import AiConfig, BehaviorConfig, PromptsConfig, SentimentConfig, TavilyConfig
from b_application.config.api_config import ApiConfig, FeaturesConfig
from b_application.config.chat_config import ChatConfig, LineConfig, NotificationConfig
from b_application.config.collect_config import (
    CollectRulesConfig,
    FolderConfig,
    FreshnessConfig,
    QualityFiltersConfig,
    StockPageConfig,
    WorldConfig,
)
from b_application.config.market_data_config import MarketDataConfig, MarketHoursConfig
from b_application.config.sources_config import SourcesConfig
from b_application.config.trading_config import (
    AnalysisConfig,
    HoldingsConfig,
    MarketConfig,
    MockTradingConfig,
    RankingConfig,
    ShioajiConfig,
    TechnicalConfig,
    TradingConfig,
    WatchlistConfig,
)
from b_application.config.valuation_config import ValuationConfig


class DbConfig(BaseSettings):
    """
    Where the app keeps its data: the PostgreSQL database of accounts, orders, watchlists and technical settings, and
    the Chroma folder of chat and decision memory. The database's address and credentials come from the environment or
    .env, never from a settings file, and the app refuses to start while one is missing or blank. `retired` names the
    setting this section once had and no longer reads (settings_notices).
    """

    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
        str_strip_whitespace=True,
        json_schema_extra={"retired": ["backend"]},
    )

    chroma_persist_path: str

    user: str = Field(min_length=1, validation_alias="DB_USER")
    password: str = Field(min_length=1, validation_alias="DB_PASSWORD")
    host: str = Field(min_length=1, validation_alias="DB_HOST")
    port: int = Field(default=5432, validation_alias="DB_PORT")
    name: str = Field(min_length=1, validation_alias="DB_NAME")


class AppConfig(BaseSettings):
    """
    Application and infrastructure configuration. A section with no default here comes only from config/appsetting.yaml:
    load_settings passes it, and tests read it through tests/support/settings.py.
    `retired` names the sections the file once had and the app no longer reads (settings_notices).
    """

    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
        frozen=False,
        json_schema_extra={"retired": ["strategy_search"]},
    )

    project_root: Path = Field(exclude=True)
    """Set by load_settings, never by a settings file: `exclude` marks a field the loader sets, and the key check refuses it."""

    environment: SystemEnvironment = Field(
        SystemEnvironment.DEV, json_schema_extra={"restart_only": True, "group": SettingGroup.SITE_ACCESS}
    )
    """`restart_only` marks a setting a reload or a save refuses to change: validate_started_setup_unchanged."""

    audience: Audience = Field(Audience.PERSONAL, json_schema_extra={"restart_only": True, "group": SettingGroup.SITE_ACCESS})
    """
    Whom this deployment serves, and with it which data and brokers it may use: Audience's table. `group` names the
    SettingGroup the settings form shows a setting or a whole section under; a typed setting always shows under ADVANCED.
    """

    settings_revisions: dict[SettingsFile, str] = Field(default_factory=dict, exclude=True)
    """The revision of each settings file this configuration was loaded from, set by load_settings like project_root."""

    ai: AiConfig = Field(json_schema_extra={"group": SettingGroup.AI})
    line: LineConfig = Field(default_factory=LineConfig, json_schema_extra={"group": SettingGroup.ADVANCED})
    api: ApiConfig = Field(default_factory=ApiConfig, json_schema_extra={"group": SettingGroup.ADVANCED})
    behavior: BehaviorConfig = Field(json_schema_extra={"operator_only": True})
    """
    `operator_only` marks a setting, or every setting of a section, that only an operator who edits
    config/appsetting.yaml changes: the settings form neither shows it nor accepts a change to it. The file, the load
    and the start's notices read it like any other setting.
    """

    db: DbConfig = Field(json_schema_extra={"operator_only": True})
    chat: ChatConfig = Field(json_schema_extra={"operator_only": True})
    folder: FolderConfig = Field(default_factory=FolderConfig, json_schema_extra={"operator_only": True})
    tavily: TavilyConfig = Field(default_factory=TavilyConfig, json_schema_extra={"group": SettingGroup.AI})
    analysis: AnalysisConfig = Field(json_schema_extra={"group": SettingGroup.TRADING_LIMITS})
    technical: TechnicalConfig = Field(json_schema_extra={"group": SettingGroup.TRADING_LIMITS})
    ranking: RankingConfig = Field(json_schema_extra={"group": SettingGroup.RANKING})
    notifications: NotificationConfig = Field(
        default_factory=NotificationConfig, json_schema_extra={"group": SettingGroup.TRADING_LIMITS}
    )
    prompts: PromptsConfig = Field(default_factory=PromptsConfig, json_schema_extra={"group": SettingGroup.AI})
    sentiment: SentimentConfig = Field(default_factory=SentimentConfig, json_schema_extra={"group": SettingGroup.DATA_HISTORY})
    collect_rules: CollectRulesConfig = Field(json_schema_extra={"operator_only": True})
    quality: QualityFiltersConfig = Field(default_factory=QualityFiltersConfig, json_schema_extra={"group": SettingGroup.DATA_HISTORY})
    stock_page: StockPageConfig = Field(default_factory=StockPageConfig, json_schema_extra={"group": SettingGroup.DATA_HISTORY})
    world: WorldConfig = Field(default_factory=WorldConfig, json_schema_extra={"group": SettingGroup.DATA_HISTORY})
    market: MarketConfig = Field(json_schema_extra={"group": SettingGroup.TRADING_LIMITS})
    freshness: FreshnessConfig = Field(default_factory=FreshnessConfig, json_schema_extra={"group": SettingGroup.DATA_HISTORY})
    market_hours: MarketHoursConfig = Field(default_factory=MarketHoursConfig, json_schema_extra={"operator_only": True})
    market_data: MarketDataConfig = Field(default_factory=MarketDataConfig, json_schema_extra={"group": SettingGroup.DATA_HISTORY})
    trading: TradingConfig = Field(json_schema_extra={"group": SettingGroup.TRADING_LIMITS})
    mock_trading: MockTradingConfig = Field(
        default_factory=MockTradingConfig, json_schema_extra={"group": SettingGroup.TRADING_LIMITS}
    )
    shioaji: ShioajiConfig = Field(json_schema_extra={"group": SettingGroup.TRADING_LIMITS})
    holdings: HoldingsConfig = Field(default_factory=HoldingsConfig, json_schema_extra={"group": SettingGroup.TRADING_LIMITS})
    watchlist: WatchlistConfig = Field(default_factory=WatchlistConfig, json_schema_extra={"group": SettingGroup.DATA_HISTORY})
    valuation: ValuationConfig = Field(json_schema_extra={"group": SettingGroup.AI})
    accounts: AccountsConfig = Field(json_schema_extra={"group": SettingGroup.SITE_ACCESS})
    sources: SourcesConfig = Field(json_schema_extra={"operator_only": True})
    features: FeaturesConfig = Field(default_factory=FeaturesConfig, json_schema_extra={"group": SettingGroup.FEATURES})

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

    def backtest_rule(self, buy_score: int, sell_score: int) -> BacktestRule:
        """
        The replay of one backtest: the live decisions, costs and stop-loss as configured, but for the two scores, which
        each backtest chooses in place of analysis.min_combined_score_buy and analysis.max_combined_score_sell.
        """
        live = self.run_decisions_rule()
        decision_rule = replace(
            live.decision_rule,
            entry_rule=replace(live.decision_rule.entry_rule, buy_threshold=buy_score),
            exit_rule=replace(live.decision_rule.exit_rule, sell_threshold=sell_score),
        )

        return BacktestRule(
            buy_score=buy_score,
            run_decisions_rule=replace(live, decision_rule=decision_rule),
            open_fill_rule=OpenFillRule(
                lot_size=self.analysis.lot_size, affordable_quantity_rule=AffordableQuantityRule(cost_rule=self.market.cost_rule())
            ),
            session_stop_loss_rule=SessionStopLossRule(stop_loss_rule=self.stop_loss_rule()),
            cost_rule=self.market.cost_rule(),
            position_value_rule=self.market.position_value_rule(),
        )

    def brief_writing(self, kind: BriefKind) -> tuple[str, int, int, BriefReplyRule]:
        """
        What DailyStockBrief writes a kind of text from: its prompt, the most sentences it keeps, the stocks that may
        get a new one a day at viewers' requests, and its reply contract. The world brief is one text a day.
        """
        brief, card, world, advice = self.stock_page.brief, self.stock_page.card, self.world.brief, self.prompts.advice_phrases()

        match kind:
            case BriefKind.MOVEMENT:
                return self.prompts.stock_brief, brief.sentences, brief.daily_stocks, brief.reply_rule(advice)
            case BriefKind.COMPANY:
                return self.prompts.company_card, card.sentences, card.daily_stocks, card.reply_rule(advice, brief.link_pattern)
            case BriefKind.WORLD:
                return self.prompts.world_brief, world.sentences, 1, world.reply_rule(advice, brief.link_pattern)

    def world_brief_due_rule(self) -> WorldBriefDueRule:
        """
        When the day's world brief is asked for. The site writes one only while its own writing is on
        (stock_page.system_writing), prompts.world_brief is set and features.world shows the world to somebody.
        """
        shown = self.features.visibility(Feature.WORLD).shown_to(frozenset(Permission))
        on = shown and self.stock_page.system_writing.enabled and bool(self.prompts.world_brief)

        return self.world.brief.due_rule(on, self.stock_page.brief.claim_minutes)

    def company_card_context_rule(self) -> CompanyCardContextRule:
        """What a company card rests on; its prompt and language are part of what a card is written from."""
        return CompanyCardContextRule(
            section_length=self.stock_page.card.section_length,
            industry_names=self.sources.exchange.industry_names,
            instructions=f"{self.stock_page.brief.language.value}\n{self.prompts.company_card}",
        )

    def decision_sessions_rule(self) -> DecisionSessionsRule:
        """The ranking's decision sessions, each reading the newest month of revenue due before it."""
        return DecisionSessionsRule(decision_day=self.ranking.decision_day, deadline_day=self.sources.mops.revenue_deadline_day)

    def ranking_portfolio_rule(self) -> RankingPortfolioRule:
        """How given rankings are held: the market's fee on every trade and its stock tax on every sale, against the benchmark."""
        return RankingPortfolioRule(
            fee_rate=self.market.fee_rate,
            tax_rate=self.market.tax_rate,
            benchmark_id=self.ranking.benchmark_id,
            sessions_per_year=self.ranking.sessions_per_year,
        )

    def ranking_backtest_rule(self, formula: RankingFormula) -> RankingBacktestRule:
        """A formula's replay: its ranking at each decision session, held as ranking_portfolio_rule holds them."""
        return RankingBacktestRule(
            decision_rule=self.decision_sessions_rule(),
            ranking_rule=MonthlyRankingRule(formula=formula, benchmark_id=self.ranking.benchmark_id),
            portfolio_rule=self.ranking_portfolio_rule(),
        )

    def follow_schedule_rule(self) -> FollowScheduleRule:
        """Where a user's scheduled ranking follow stands: the ranking's decisions, this site's order window, the times offered."""
        return FollowScheduleRule(
            decision_rule=self.decision_sessions_rule(),
            time_rule=FollowTimeRule(pricing=self.audience.order_pricing),
            times=self.ranking.follow_times,
        )

    def ranking_follow_rule(self) -> RankingFollowRule:
        """RankingFollowSignals' rule: the mock account's lot size, the order's limit and the market's fee and tax."""
        return RankingFollowRule(
            lot_size=self.analysis.lot_size,
            limit_price_rule=self.market.limit_price_rule(),
            affordable_quantity_rule=AffordableQuantityRule(cost_rule=self.market.cost_rule()),
        )

    def manual_entry_rule(self) -> ManualEntryRule:
        """ManualSignal's rule: the confirmed BUY skips the buy threshold, never the sizing."""
        return ManualEntryRule(sizing_rule=self.sizing_rule())

    def order_rule(self) -> OrderRule:
        price_rule = OrderPriceRule(pricing=self.audience.order_pricing, price_freshness=self.freshness.realtime_rule())

        return OrderRule(gate_rule=OrderGateRule(price_rule=price_rule), limit_price_rule=self.market.limit_price_rule())

    def broker_access_rule(self) -> BrokerAccessRule:
        """
        OrderPreparation's check at the send: the brokers both the audience and its order pricing offer and the
        environment's server. Whom features.* lets order on a broker is no part of it: OrderPreparation reads that from
        the site's ordering switch at each send.
        """
        limit_rule = BuyLimitRule(max_order_value=self.trading.max_order_value, max_daily_buy_value=self.trading.max_daily_buy_value)

        return BrokerAccessRule(
            brokers=self.audience.brokers & self.audience.order_pricing.brokers,
            orderer_rule=RealBrokerOrdererRule(),
            login_rule=BrokerLoginRule(simulation=self.environment.shioaji_simulation),
            limit_rule=limit_rule,
        )

    def registration_rule(self) -> RegistrationRule:
        """The sign-up screen and the registration both ask it, so they never disagree."""
        return RegistrationRule(registration_open=self.accounts.registration_open)
