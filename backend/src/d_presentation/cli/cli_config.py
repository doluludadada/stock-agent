# backend/src/d_presentation/cli/cli_config.py
from a_domain.model.trading.signal import TradeSignal
from a_domain.ports.trading.execution_provider import IExecutionProvider
from a_domain.types.enums import SystemEnvironment
from b_application.pipeline import Pipeline
from d_presentation.dependencies.core import (
    get_db_connector,
    get_logger,
    get_notification_provider,
    get_settings,
)
from d_presentation.dependencies.providers import (
    get_indicator_provider,
    get_news_provider,
    get_price_provider,
    get_stock_provider,
    get_tavily_search,
)
from d_presentation.dependencies.repositories import (
    get_ai_provider,
    get_chroma_repository,
    get_conversation_repository,
    get_knowledge_repository,
    get_signal_repository,
    get_watchlist_repository,
)
from d_presentation.dependencies.rules import (
    get_ai_report_parser,
    get_ai_report_prompt_builder,
    get_composite_score_rule,
    get_data_freshness_rule,
    get_decision_rule,
    get_exit_rule,
    get_quality_rule,
    get_technical_score_calculator,
    get_technical_screening_policy,
)
from d_presentation.dependencies.use_cases import (
    get_ai_analyser_use_case,
    get_market_data_use_case,
    get_monitoring_use_case,
    get_news_feed_use_case,
    get_order_execution_use_case,
    get_pipeline,
    get_reporting_use_case,
    get_signals_use_case,
    get_stock_selector_use_case,
    get_technical_filter_use_case,
)


class MockExecutionProvider(IExecutionProvider):
    """
    Temporary mock so the CLI can run end-to-end without crashing
    on `NotImplementedError` raised in repositories.py.
    """
    async def get_portfolio_value(self) -> float:
        return 1000000.0

    async def get_buying_power(self) -> float:
        return 1000000.0

    async def get_positions(self) -> list:
        return []

    async def submit_order(self, signal: TradeSignal) -> bool:
        return True


def build_pipeline(env_override: str = "") -> Pipeline:
    """Manually assembles the application graph for the CLI."""
    config = get_settings()

    if env_override:
        try:
            config.environment = SystemEnvironment(env_override.lower())
        except ValueError:
            pass  # Fallback to current config

    logger = get_logger.__wrapped__(config=config)
    connector = get_db_connector.__wrapped__(config=config, logger=logger)

    # Core & infra
    notification = get_notification_provider.__wrapped__(config=config, logger=logger)
    indicators = get_indicator_provider.__wrapped__(config=config)

    # External APIs
    tavily = get_tavily_search.__wrapped__(config=config, logger=logger)
    price_prov = get_price_provider.__wrapped__(logger=logger)
    stock_prov = get_stock_provider.__wrapped__(logger=logger)
    news_prov = get_news_provider.__wrapped__(config=config, logger=logger)

    # DB & AI Integrations
    ai_prov = get_ai_provider.__wrapped__(config=config, logger=logger, web_search=tavily)
    chroma_repo = get_chroma_repository.__wrapped__(config=config, logger=logger)
    convers_repo = get_conversation_repository(chroma_repo)
    knowled_repo = get_knowledge_repository(chroma_repo)
    signal_repo = get_signal_repository(connector, logger)
    watch_repo = get_watchlist_repository(connector, logger)
    
    # We inject our specific Mock ExecutionProvider here
    exec_prov = MockExecutionProvider()

    # Rules
    fresh = get_data_freshness_rule()
    qual = get_quality_rule(config)
    tech_calc = get_technical_score_calculator(config)
    tech_pol = get_technical_screening_policy(config)
    prompt_b = get_ai_report_prompt_builder(config)
    parser = get_ai_report_parser()
    comp_rule = get_composite_score_rule(config)
    dec_rule = get_decision_rule(config)
    exit_rule = get_exit_rule(config)

    # Use Cases
    market = get_market_data_use_case(price_prov, fresh, config, logger)
    news = get_news_feed_use_case(news_prov, qual, config, logger)
    selector = get_stock_selector_use_case(watch_repo, logger)
    tech_fil = get_technical_filter_use_case(indicators, tech_pol, tech_calc, logger)
    ai_analyser = get_ai_analyser_use_case(ai_prov, prompt_b, parser, knowled_repo, config, logger)
    exec_uc = get_order_execution_use_case(exec_prov, config, logger)
    reporting = get_reporting_use_case(notification, config, logger)
    signals = get_signals_use_case(comp_rule, dec_rule, signal_repo, knowled_repo, logger)
    monitoring = get_monitoring_use_case(exec_prov, price_prov, stock_prov, exit_rule, logger)

    # Compose final Pipeline
    pipeline = get_pipeline(
        selector,
        market,
        tech_fil,
        news,
        ai_analyser,
        signals,
        exec_uc,
        reporting,
        monitoring,
        logger,
    )

    return pipeline
