# backend/src/d_presentation/cli/cli_container.py

from a_domain.model.trading.order import Order
from a_domain.model.trading.position import Position
from a_domain.ports.trading.execution_provider import IExecutionProvider
from a_domain.rules.collect.freshness import DataFreshnessRule
from a_domain.rules.collect.quality_rule import QualityRule
from a_domain.rules.process.ai.parser import AiReportParser
from a_domain.rules.process.ai.prompt import AiReportPromptBuilder
from a_domain.rules.process.scoring.composite import CompositeScoreRule
from a_domain.rules.process.scoring.technical import TechnicalScoreCalculator
from a_domain.rules.trading.action import ActionRule
from a_domain.rules.trading.decision import DecisionRule
from a_domain.rules.trading.exit import ExitRule
from a_domain.rules.trading.reason import ReasonRule
from a_domain.rules.trading.sizing import SizingRule
from b_application.factories.policy_factory import create_conservative_policy, create_nightly_screening_policy
from b_application.pipeline import Pipeline
from b_application.use_cases.collect.market_data import MarketData
from b_application.use_cases.collect.market_scan import MarketScan
from b_application.use_cases.collect.news_feed import NewsFeed
from b_application.use_cases.collect.stock_selector import StockSelector
from b_application.use_cases.collect.watchlist import Watchlist
from b_application.use_cases.process.ai_analyser import AiAnalyser
from b_application.use_cases.process.technical_filter import TechnicalFilter
from b_application.use_cases.ship.reporting import Reporting
from b_application.use_cases.ship.signals import Signals
from b_application.use_cases.trade.monitoring import Monitoring
from b_application.use_cases.trade.order_execution import OrderExecution
from b_application.workflow import WorkflowOrchestrator
from c_infrastructure.ai_models.factory import AiAdapterFactory
from c_infrastructure.database.chroma.chroma_repository import ChromaRepositoryAdapter
from c_infrastructure.database.db_connector import DatabaseConnector
from c_infrastructure.database.repositories.signal_repository import SignalRepository
from c_infrastructure.database.repositories.watchlist_repository import WatchlistRepository
from c_infrastructure.feed.news_provider import NewsProvider
from c_infrastructure.feed.ptt_provider import PttProvider
from c_infrastructure.feed.tavily_provider import TavilySearchAdapter
from c_infrastructure.market.indicator_provider import IndicatorProvider
from c_infrastructure.market.twse_provider import TaiwanStockProvider
from c_infrastructure.market.cached_price_provider import CachedPriceProvider
from c_infrastructure.market.yahoo_finance_adapter import YahooFinanceProvider
from c_infrastructure.platforms.line.line_notification_adapter import LineNotificationAdapter
from c_infrastructure.system.config_loader import load_settings
from c_infrastructure.system.logger_service import LoggerService


class MockExecutionProvider(IExecutionProvider):
    """Correctly implements the IExecutionProvider interface for CLI dev runs."""

    async def place_order(self, order: Order) -> str:
        return "mock_order_123"

    async def cancel_order(self, order_id: str) -> bool:
        return True

    async def get_positions(self) -> list[Position]:
        return []

    async def get_cash_balance(self) -> float:
        return 1000.0


async def build_cli_orchestrator() -> WorkflowOrchestrator:
    """Pure Python dependency injection factory. No FastAPI wrappers here."""

    # 1. Config & System
    config = load_settings()
    logger = LoggerService(level=config.behavior.log_level)

    # 2. Database & Repositories
    db = DatabaseConnector(config, logger)
    await db.init_db()

    watchlist_repo = WatchlistRepository(db, logger)
    signal_repo = SignalRepository(db, logger)
    knowledge_db = ChromaRepositoryAdapter(config, logger)
    await knowledge_db.init()

    # 3. External Providers
    stock_provider = TaiwanStockProvider(logger)
    yahoo_provider = YahooFinanceProvider(logger)
    price_provider = CachedPriceProvider(yahoo_provider, db, logger)
    indicator_provider = IndicatorProvider(config)
    news_provider = NewsProvider(config, logger)
    social_provider = PttProvider(config, logger, stock_provider)
    web_search = TavilySearchAdapter(config, logger) if config.tavily.api_key else None

    # 4. AI & Actions
    ai_factory = AiAdapterFactory(config, logger, web_search)
    ai_provider = ai_factory.create_adapter()
    notification = LineNotificationAdapter(config, logger) if config.line.channel_access_token else None
    broker = MockExecutionProvider()

    # 5. Domain Rules & Policies
    nightly_policy = create_nightly_screening_policy(config.strategy)
    intraday_policy = create_conservative_policy(config.strategy)

    freshness_rule = DataFreshnessRule(max_lag_minutes=2880)

    quality_rule = QualityRule(
        spam_keywords=frozenset(config.collect_rules.spam_keywords),
        financial_keywords=frozenset(),
        min_chars_stock=config.quality.min_chars_stock,
        min_chars_news=config.quality.min_chars_news,
        min_chars_gossip=config.quality.min_chars_gossip,
    )

    tech_calculator = TechnicalScoreCalculator(
        base=config.scoring.base,
        pass_bonus=config.scoring.pass_bonus,
        hard_failure_penalty=config.scoring.hard_failure_penalty,
        max_hard_penalty=config.scoring.max_hard_penalty,
        soft_failure_penalty=config.scoring.soft_failure_penalty,
        max_soft_penalty=config.scoring.max_soft_penalty,
        rsi_sweet_spot_bonus=config.scoring.rsi_sweet_spot_bonus,
        rsi_sweet_spot_min=config.scoring.rsi_sweet_spot_min,
        rsi_sweet_spot_max=config.scoring.rsi_sweet_spot_max,
        macd_bullish_bonus=config.scoring.macd_bullish_bonus,
        ma_present_bonus=config.scoring.ma_present_bonus,
    )

    prompt_builder = AiReportPromptBuilder(
        fundamental_template=config.prompts.analysis_report_fundamental,
        momentum_template=config.prompts.analysis_report_momentum,
        max_articles=config.analysis.article_fetch_limit,
        max_content_length=config.ai.article_content_length,
    )

    decision_rule = DecisionRule(
        action_rule=ActionRule(
            buy_threshold=config.analysis.min_combined_score_buy, sell_threshold=config.analysis.max_combined_score_sell
        ),
        reason_rule=ReasonRule(),
        sizing_rule=SizingRule(),
        total_capital=config.analysis.total_capital,
        risk_pct=config.analysis.risk_per_trade_pct,
    )

    exit_rule = ExitRule(stop_loss_pct=config.analysis.stop_loss_pct)

    # 6. Instantiate Use Cases
    uc_watchlist = Watchlist(stock_provider, price_provider, watchlist_repo, indicator_provider, nightly_policy, logger, config)
    uc_market_scan = MarketScan(social_provider, watchlist_repo, logger, config)
    uc_selector = StockSelector(watchlist_repo, stock_provider, logger)
    uc_data = MarketData(price_provider, freshness_rule, config, logger)
    uc_tech = TechnicalFilter(indicator_provider, intraday_policy, tech_calculator, logger)
    uc_news = NewsFeed(news_provider, quality_rule, config, logger)
    uc_ai = AiAnalyser(ai_provider, prompt_builder, AiReportParser(), knowledge_db, config, logger)
    uc_signals = Signals(
        CompositeScoreRule(config.analysis.technical_weight, config.analysis.sentiment_weight),
        decision_rule,
        signal_repo,
        knowledge_db,
        logger,
    )
    uc_exec = OrderExecution(broker, config, logger)
    uc_report = Reporting(notification, config, logger)
    uc_monitor = Monitoring(broker, price_provider, stock_provider, exit_rule, logger)

    # 7. Assemble Pipeline & Orchestrator
    pipeline = Pipeline(uc_selector, uc_data, uc_tech, uc_news, uc_ai, uc_signals, uc_exec, uc_report, uc_monitor, logger)

    return WorkflowOrchestrator(uc_watchlist, uc_market_scan, pipeline, logger, db=db)
