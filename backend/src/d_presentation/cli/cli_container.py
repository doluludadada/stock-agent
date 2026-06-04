# backend/src/d_presentation/cli/cli_container.py


from a_domain.rules.ai.parser import AiReportParser
from a_domain.rules.ai.prompt import AiReportPromptBuilder
from a_domain.rules.collect import CandidateSelectionRule
from a_domain.rules.collect.article_quality import ArticleQualityRule
from a_domain.rules.collect.freshness import DataFreshnessRule
from a_domain.rules.scoring.composite import CompositeScoreRule
from a_domain.rules.scoring.technical import TechnicalScoreCalculator
from a_domain.rules.trading.action import ActionRule
from a_domain.rules.trading.decision import DecisionRule
from a_domain.rules.trading.entry import EntryRule
from a_domain.rules.trading.exit import ExitRule
from a_domain.rules.trading.reason import ReasonRule
from a_domain.rules.trading.sizing import SizingRule
from b_application.factories import TechnicalPolicyFactory
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
from b_application.use_cases.trade.account_loader import AccountLoader
from b_application.use_cases.trade.account_risk_check import AccountRiskCheck
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
from c_infrastructure.market.cached_price_provider import CachedPriceProvider
from c_infrastructure.market.indicator_provider import IndicatorProvider
from c_infrastructure.market.twse_provider import TaiwanStockProvider
from c_infrastructure.market.yahoo_finance_adapter import YahooFinanceProvider
from c_infrastructure.platforms.line.line_notification_adapter import LineNotificationAdapter
from c_infrastructure.system.config_loader import load_settings
from c_infrastructure.system.logger_service import LoggerService
from c_infrastructure.trading.mock.mock_execution_provider import MockExecutionProvider


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
    price_provider = CachedPriceProvider(price_provider=yahoo_provider, db=db, logger=logger)
    indicator_provider = IndicatorProvider(config)
    news_provider = NewsProvider(config, logger)
    social_provider = PttProvider(config=config, logger=logger, stock_provider=stock_provider)
    web_search_provider = TavilySearchAdapter(config, logger) if config.tavily.api_key else None

    # 4. AI & Actions
    ai_factory = AiAdapterFactory(config=config, logger=logger, web_search_provider=web_search_provider)
    ai_provider = ai_factory.create_adapter()
    notification = LineNotificationAdapter(config, logger) if config.line.channel_access_token else None
    broker = MockExecutionProvider(
        db=db,
        config=config,
        logger=logger,
    )
    # 5. Domain Rules & Policies
    policy_factory = TechnicalPolicyFactory()
    nightly_policy = policy_factory.create_nightly(config.strategy)
    intraday_policy = policy_factory.create_conservative(config.strategy)

    freshness_rule = DataFreshnessRule(max_lag_minutes=2880)
    candidate_selection_rule = CandidateSelectionRule()

    quality_rule = ArticleQualityRule(
        spam_keywords=frozenset(config.collect_rules.spam_keywords),
        financial_keywords=frozenset(config.collect_rules.financial_keywords),
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

    action_rule = ActionRule(
        buy_threshold=config.analysis.min_combined_score_buy,
        sell_threshold=config.analysis.max_combined_score_sell,
    )

    reason_rule = ReasonRule()

    sizing_rule = SizingRule(
        position_pct=config.analysis.risk_per_trade_pct,
        lot_size=1,
    )

    entry_rule = EntryRule(
        action_rule=action_rule,
        sizing_rule=sizing_rule,
        reason_rule=reason_rule,
    )

    exit_rule = ExitRule(
        stop_loss_pct=config.analysis.stop_loss_pct,
        action_rule=action_rule,
        reason_rule=reason_rule,
    )

    decision_rule = DecisionRule(
        entry_rule=entry_rule,
        exit_rule=exit_rule,
    )

    # 6. Instantiate Use Cases
    uc_watchlist = Watchlist(
        stock_provider=stock_provider,
        price_provider=price_provider,
        watchlist_repo=watchlist_repo,
        indicator_provider=indicator_provider,
        screening_policy=nightly_policy,
        logger=logger,
        config=config,
    )
    uc_market_scan = MarketScan(
        social_media_provider=social_provider,
        watchlist_repo=watchlist_repo,
        logger=logger,
        config=config,
    )
    uc_account_loader = AccountLoader(
        execution_provider=broker,
        stock_provider=stock_provider,
        logger=logger,
    )
    uc_account_risk_check = AccountRiskCheck(
        price_provider=price_provider,
        exit_rule=exit_rule,
        logger=logger,
    )
    uc_selector = StockSelector(
        watchlist_repo=watchlist_repo,
        stock_provider=stock_provider,
        candidate_selection_rule=candidate_selection_rule,
        logger=logger,
    )
    uc_data = MarketData(
        price=price_provider,
        freshness_rule=freshness_rule,
        config=config,
        logger=logger,
    )
    uc_tech = TechnicalFilter(
        indicator_provider=indicator_provider,
        screening_policy=intraday_policy,
        score_calculator=tech_calculator,
        logger=logger,
    )
    uc_news = NewsFeed(
        news_provider=news_provider,
        quality_filter=quality_rule,
        config=config,
        logger=logger,
    )
    uc_ai = AiAnalyser(
        ai_provider=ai_provider,
        prompt_builder=prompt_builder,
        response_parser=AiReportParser(),
        knowledge_repo=knowledge_db,
        config=config,
        logger=logger,
    )
    uc_signals = Signals(
        decision_rule=decision_rule,
        composite_rule=CompositeScoreRule(config.analysis.technical_weight, config.analysis.sentiment_weight),
        signal_repository=signal_repo,
        knowledge_repository=knowledge_db,
        logger=logger,
    )
    uc_exec = OrderExecution(
        execution_provider=broker,
        logger=logger,
    )
    uc_report = Reporting(
        notification_provider=notification,
        config=config,
        logger=logger,
    )

    # 7. Assemble Pipeline & Orchestrator
    pipeline = Pipeline(
        account_loader=uc_account_loader,
        account_risk_check=uc_account_risk_check,
        stock_selector=uc_selector,
        market_data=uc_data,
        technical_filter=uc_tech,
        news_feed=uc_news,
        ai_analyser=uc_ai,
        signals=uc_signals,
        order_execution=uc_exec,
        reporting=uc_report,
        logger=logger,
    )

    return WorkflowOrchestrator(uc_watchlist, uc_market_scan, pipeline, logger, db=db)
