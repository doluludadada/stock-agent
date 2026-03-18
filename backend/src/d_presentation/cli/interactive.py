import asyncio
import sys

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt

# --- Domain Imports ---
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

# --- Application Imports ---
from b_application.factories.policy_factory import create_conservative_policy, create_nightly_screening_policy
from b_application.pipeline import Pipeline
from b_application.schemas.pipeline_context import PipelineContext
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
from c_infrastructure.database.db_connector import DatabaseConnector
from c_infrastructure.database.repositories.signal_repository import SignalRepository
from c_infrastructure.database.repositories.watchlist_repository import WatchlistRepository
from c_infrastructure.feed.news_provider import NewsProvider
from c_infrastructure.feed.ptt_provider import PttProvider
from c_infrastructure.feed.tavily_provider import TavilySearchAdapter
from c_infrastructure.market.indicator_provider import IndicatorProvider
from c_infrastructure.market.twse_provider import TaiwanStockProvider
from c_infrastructure.market.yahoo_finance_adapter import YahooFinanceProvider
from c_infrastructure.platforms.line.line_notification_adapter import LineNotificationAdapter

# --- Infrastructure Imports ---
from c_infrastructure.system.config_loader import load_settings
from c_infrastructure.system.logger_service import LoggerService

console = Console()


class DummyExecutionProvider:
    """A mock broker for CLI testing so we don't need real API keys yet."""

    async def place_order(self, order) -> str:
        return "mock_order_123"

    async def cancel_order(self, order_id: str) -> bool:
        return True

    async def get_positions(self) -> list:
        return []

    async def get_cash_balance(self) -> float:
        return 1000000.0


class DummyKnowledgeRepo:
    """Mock Chroma RAG memory for testing."""

    async def search(self, query: str, limit: int = 3) -> str:
        return ""

    async def save_analysis(self, context) -> None:
        pass


async def setup_dependencies():
    """Manual Dependency Injection Wiring."""
    config = load_settings()
    logger = LoggerService(level=config.behavior.log_level)

    # DB
    db = DatabaseConnector(config, logger)
    await db.init_db()

    # Repositories
    watchlist_repo = WatchlistRepository(db, logger)
    signal_repo = SignalRepository(db, logger)
    knowledge_repo = DummyKnowledgeRepo()

    # Providers
    stock_provider = TaiwanStockProvider(logger)
    price_provider = YahooFinanceProvider(logger)
    indicator_provider = IndicatorProvider(config)
    news_provider = NewsProvider(config, logger)
    social_provider = PttProvider(config, logger)
    web_search = TavilySearchAdapter(config, logger) if config.tavily.api_key else None

    # AI
    ai_factory = AiAdapterFactory(config, logger, web_search)
    ai_provider = ai_factory.create_adapter()

    # Notifications & Broker
    notification = LineNotificationAdapter(config, logger) if config.line.channel_access_token else None
    broker = DummyExecutionProvider()

    # Policies & Rules
    nightly_policy = create_nightly_screening_policy(config.strategy)
    intraday_policy = create_conservative_policy(config.strategy)
    freshness_rule = DataFreshnessRule(max_lag_minutes=2880)
    quality_rule = QualityRule(
        spam_keywords=config.collect_rules.spam_keywords,
        financial_keywords=set(),
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
        fundamental_template=config.prompts.analysis_report_fundamental or "Analyze {stock_id}: {articles_text}",
        momentum_template=config.prompts.analysis_report_momentum or "Analyze hype {stock_id}: {articles_text}",
        max_articles=config.analysis.article_fetch_limit,
        max_content_length=config.ai.article_content_length,
    )
    decision_rule = DecisionRule(
        ActionRule(buy_threshold=config.analysis.min_combined_score_buy, sell_threshold=config.analysis.max_combined_score_sell),
        ReasonRule(),
        SizingRule(),
        total_capital=config.analysis.total_capital,
        risk_pct=config.analysis.risk_per_trade_pct,
    )

    # Use Cases
    uc_watchlist = Watchlist(stock_provider, price_provider, watchlist_repo, indicator_provider, nightly_policy, logger, config)
    uc_market_scan = MarketScan(social_provider, watchlist_repo, logger, config)
    uc_selector = StockSelector(watchlist_repo, logger)
    uc_data = MarketData(price_provider, freshness_rule, config, logger)
    uc_tech = TechnicalFilter(indicator_provider, intraday_policy, tech_calculator, logger)
    uc_news = NewsFeed(news_provider, quality_rule, config, logger)
    uc_ai = AiAnalyser(ai_provider, prompt_builder, AiReportParser(), knowledge_repo, config, logger)
    uc_signals = Signals(
        CompositeScoreRule(config.analysis.technical_weight, config.analysis.sentiment_weight),
        decision_rule,
        signal_repo,
        knowledge_repo,
        logger,
    )
    uc_exec = OrderExecution(broker, config, logger)
    uc_report = Reporting(notification, config, logger)
    uc_monitor = Monitoring(broker, price_provider, stock_provider, ExitRule(config.analysis.stop_loss_pct), logger)

    pipeline = Pipeline(uc_selector, uc_data, uc_tech, uc_news, uc_ai, uc_signals, uc_exec, uc_report, uc_monitor, logger)
    orchestrator = WorkflowOrchestrator(uc_watchlist, uc_market_scan, pipeline, logger)

    return orchestrator


async def interactive_menu():
    console.print(Panel.fit("[bold cyan]TW-Stock-Alpha-Agent CLI[/bold cyan]", border_style="cyan"))

    console.print("[yellow]Booting up and wiring dependencies...[/yellow]")
    orchestrator = await setup_dependencies()
    console.print("[green]System Ready![/green]\n")

    while True:
        console.print("[1] Run Full Cycle (WARNING: Scans 1700+ stocks, slow!)")
        console.print("[2] Phase 1: Run Nightly Tech Scan (Update DB)")
        console.print("[3] Phase 2: Run Morning Buzz Scan (Update DB)")
        console.print("[4] Phase 3: Run Intraday Pipeline (Process DB Watchlists)")
        console.print("[5] Target Mode: Manually test a specific stock (e.g., 2330)")
        console.print("[0] Exit")

        choice = Prompt.ask("Select an option", choices=["0", "1", "2", "3", "4", "5"])

        if choice == "0":
            break

        context = PipelineContext()

        if choice == "1":
            await orchestrator.run_full_cycle()
        elif choice == "2":
            await orchestrator.run_nightly(context)
        elif choice == "3":
            await orchestrator.run_buzz_scan(context)
        elif choice == "4":
            await orchestrator.run_intraday(context)
        elif choice == "5":
            symbols = Prompt.ask("Enter stock symbols separated by space (e.g. '2330 2317')")
            symbol_list = [s.strip() for s in symbols.split()]
            context.manual_symbols = symbol_list
            await orchestrator.run_intraday(context)

        console.print("\n[bold green]Execution Complete![/bold green]")
        if context.buy_signals:
            for sig in context.buy_signals:
                console.print(f"💰 Signal Generated: {sig.action.value} {sig.stock_id} (Score: {sig.score})")
        else:
            console.print("No actionable signals generated.")
        print("\n" + "=" * 50 + "\n")


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(interactive_menu())
