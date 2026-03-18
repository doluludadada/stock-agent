from fastapi import Depends

from a_domain.ports.ai.ai_provider import IAiProvider
from a_domain.ports.ai.knowledge_repository import IKnowledgeRepository
from a_domain.ports.analysis.indicator_provider import IIndicatorProvider
from a_domain.ports.market.news_provider import INewsProvider
from a_domain.ports.market.price_provider import IPriceProvider
from a_domain.ports.market.stock_provider import IStockProvider
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.system.notification_provider import INotificationProvider
from a_domain.ports.trading.execution_provider import IExecutionProvider
from a_domain.ports.trading.signal_repository import ISignalRepository
from a_domain.ports.trading.watchlist_repository import IWatchlistRepository
from a_domain.rules.collect.freshness import DataFreshnessRule
from a_domain.rules.collect.quality_rule import QualityRule
from a_domain.rules.process.ai.parser import AiReportParser
from a_domain.rules.process.ai.prompt import AiReportPromptBuilder
from a_domain.rules.process.policies.technical_screening import TechnicalScreeningPolicy
from a_domain.rules.process.scoring.composite import CompositeScoreRule
from a_domain.rules.process.scoring.technical import TechnicalScoreCalculator
from a_domain.rules.trading.decision import DecisionRule
from a_domain.rules.trading.exit import ExitRule
from b_application.pipeline import Pipeline
from b_application.schemas.config import AppConfig
from b_application.use_cases.collect.market_data import MarketData
from b_application.use_cases.collect.news_feed import NewsFeed
from b_application.use_cases.collect.stock_selector import StockSelector
from b_application.use_cases.process.ai_analyser import AiAnalyser
from b_application.use_cases.process.technical_filter import TechnicalFilter
from b_application.use_cases.ship.reporting import Reporting
from b_application.use_cases.ship.signals import Signals
from b_application.use_cases.trade.monitoring import Monitoring
from b_application.use_cases.trade.order_execution import OrderExecution
from d_presentation.dependencies.core import (
    get_logger,
    get_notification_provider,
    get_settings,
)
from d_presentation.dependencies.providers import get_indicator_provider, get_news_provider, get_price_provider, get_stock_provider
from d_presentation.dependencies.repositories import (
    get_ai_provider,
    get_execution_provider,
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


def get_market_data_use_case(
    price_provider: IPriceProvider = Depends(get_price_provider),
    freshness_rule: DataFreshnessRule = Depends(get_data_freshness_rule),
    config: AppConfig = Depends(get_settings),
    logger: ILoggingProvider = Depends(get_logger),
) -> MarketData:
    return MarketData(
        market_provider=price_provider,
        freshness_rule=freshness_rule,
        config=config,
        logger=logger,
    )


def get_news_feed_use_case(
    news_provider: INewsProvider = Depends(get_news_provider),
    quality_rule: QualityRule = Depends(get_quality_rule),
    config: AppConfig = Depends(get_settings),
    logger: ILoggingProvider = Depends(get_logger),
) -> NewsFeed:
    return NewsFeed(
        news_provider=news_provider,
        quality_filter=quality_rule,
        config=config,
        logger=logger,
    )


def get_stock_selector_use_case(
    watchlist_repo: IWatchlistRepository = Depends(get_watchlist_repository),
    logger: ILoggingProvider = Depends(get_logger),
) -> StockSelector:
    return StockSelector(watchlist_repo=watchlist_repo, logger=logger)


def get_technical_filter_use_case(
    indicator_provider: IIndicatorProvider = Depends(get_indicator_provider),
    screening_policy: TechnicalScreeningPolicy = Depends(get_technical_screening_policy),
    score_calculator: TechnicalScoreCalculator = Depends(get_technical_score_calculator),
    logger: ILoggingProvider = Depends(get_logger),
) -> TechnicalFilter:
    return TechnicalFilter(
        tech_provider=indicator_provider,
        screening_policy=screening_policy,
        score_calculator=score_calculator,
        logger=logger,
    )


def get_ai_analyser_use_case(
    ai_provider: IAiProvider = Depends(get_ai_provider),
    prompt_builder: AiReportPromptBuilder = Depends(get_ai_report_prompt_builder),
    response_parser: AiReportParser = Depends(get_ai_report_parser),
    knowledge_repo: IKnowledgeRepository = Depends(get_knowledge_repository),
    config: AppConfig = Depends(get_settings),
    logger: ILoggingProvider = Depends(get_logger),
) -> AiAnalyser:
    return AiAnalyser(
        ai_provider=ai_provider,
        prompt_builder=prompt_builder,
        response_parser=response_parser,
        knowledge_repo=knowledge_repo,
        config=config,
        logger=logger,
    )


def get_order_execution_use_case(
    execution_provider: IExecutionProvider = Depends(get_execution_provider),
    config: AppConfig = Depends(get_settings),
    logger: ILoggingProvider = Depends(get_logger),
) -> OrderExecution:
    return OrderExecution(
        execution_provider=execution_provider,
        config=config,
        logger=logger,
    )


def get_reporting_use_case(
    notification_provider: INotificationProvider = Depends(get_notification_provider),
    config: AppConfig = Depends(get_settings),
    logger: ILoggingProvider = Depends(get_logger),
) -> Reporting:
    return Reporting(
        notification_provider=notification_provider,
        config=config,
        logger=logger,
    )


def get_signals_use_case(
    composite_rule: CompositeScoreRule = Depends(get_composite_score_rule),
    decision_rule: DecisionRule = Depends(get_decision_rule),
    signal_repo: ISignalRepository = Depends(get_signal_repository),
    knowledge_repo: IKnowledgeRepository = Depends(get_knowledge_repository),
    logger: ILoggingProvider = Depends(get_logger),
) -> Signals:
    return Signals(
        composite_rule=composite_rule,
        decision_rule=decision_rule,
        signal_repo=signal_repo,
        knowledge_repo=knowledge_repo,
        logger=logger,
    )


def get_monitoring_use_case(
    broker_provider: IExecutionProvider = Depends(get_execution_provider),
    market_provider: IPriceProvider = Depends(get_price_provider),
    stock_provider: IStockProvider = Depends(get_stock_provider),
    exit_rule: ExitRule = Depends(get_exit_rule),
    logger: ILoggingProvider = Depends(get_logger),
) -> Monitoring:
    return Monitoring(
        broker_provider=broker_provider,
        market_provider=market_provider,
        stock_provider=stock_provider,
        exit_rule=exit_rule,
        logger=logger,
    )


def get_pipeline(
    stock_selector: StockSelector = Depends(get_stock_selector_use_case),
    market_data: MarketData = Depends(get_market_data_use_case),
    technical_filter: TechnicalFilter = Depends(get_technical_filter_use_case),
    news_feed: NewsFeed = Depends(get_news_feed_use_case),
    ai_analyser: AiAnalyser = Depends(get_ai_analyser_use_case),
    signals: Signals = Depends(get_signals_use_case),
    order_execution: OrderExecution = Depends(get_order_execution_use_case),
    reporting: Reporting = Depends(get_reporting_use_case),
    monitoring: Monitoring = Depends(get_monitoring_use_case),
    logger: ILoggingProvider = Depends(get_logger),
) -> Pipeline:
    return Pipeline(
        stock_selector=stock_selector,
        market_data=market_data,
        technical_filter=technical_filter,
        news_feed=news_feed,
        ai_analyser=ai_analyser,
        signals=signals,
        order_execution=order_execution,
        reporting=reporting,
        monitoring=monitoring,
        logger=logger,
    )
