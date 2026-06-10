# backend/src/d_presentation/dependencies/use_cases.py

from fastapi import Depends

from a_domain.ports.ai.ai_provider import IAiProvider
from a_domain.ports.ai.knowledge_repository import IKnowledgeRepository
from a_domain.ports.market.news_provider import INewsProvider
from a_domain.ports.market.price_provider import IOhlcvProvider
from a_domain.ports.market.social_media_provider import ISocialMediaProvider
from a_domain.ports.market.stock_provider import IStockProvider
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.system.market_clock import IMarketClock
from a_domain.ports.system.notification_provider import INotificationProvider
from a_domain.ports.trading.execution_provider import IExecutionProvider
from a_domain.ports.trading.signal_repository import ISignalRepository
from a_domain.ports.trading.watchlist_repository import IWatchlistRepository
from b_application.pipeline import AnalysisPipeline
from b_application.schemas.config import AppConfig
from b_application.use_cases.collect.buzz_scanner import BuzzScanner
from b_application.use_cases.collect.market_scanner import MarketScanner
from b_application.use_cases.collect.news_feed import NewsFeed
from b_application.use_cases.process.ai_analyser import AiAnalyser
from b_application.use_cases.process.technical_filter import TechnicalFilter
from b_application.use_cases.ship.reporting import Reporting
from b_application.use_cases.ship.signals import Signals
from b_application.use_cases.trade.account_loader import AccountLoader
from b_application.use_cases.trade.account_risk_check import AccountRiskCheck
from b_application.use_cases.trade.order_execution import OrderExecution
from b_application.workflow import TradingWorkflow
from d_presentation.dependencies.core import (
    get_logger,
    get_market_clock,
    get_notification_provider,
    get_settings,
)
from d_presentation.dependencies.providers import (
    get_news_provider,
    get_price_provider,
    get_social_media_provider,
    get_stock_provider,
)
from d_presentation.dependencies.repositories import (
    get_ai_provider,
    get_execution_provider,
    get_knowledge_repository,
    get_signal_repository,
    get_watchlist_repository,
)


def get_market_scanner_use_case(
    stock_provider: IStockProvider = Depends(get_stock_provider),
    price_provider: IOhlcvProvider = Depends(get_price_provider),
    market_clock: IMarketClock = Depends(get_market_clock),
    config: AppConfig = Depends(get_settings),
    logger: ILoggingProvider = Depends(get_logger),
) -> MarketScanner:
    return MarketScanner(
        stock_provider=stock_provider,
        Ohlcv_provider=price_provider,
        market_clock=market_clock,
        config=config,
        logger=logger,
    )


def get_buzz_scanner_use_case(
    social_media_provider: ISocialMediaProvider = Depends(get_social_media_provider),
    stock_provider: IStockProvider = Depends(get_stock_provider),
    logger: ILoggingProvider = Depends(get_logger),
    config: AppConfig = Depends(get_settings),
) -> BuzzScanner:
    return BuzzScanner(
        social_media_provider=social_media_provider,
        stock_provider=stock_provider,
        logger=logger,
        config=config,
    )


def get_news_feed_use_case(
    news_provider: INewsProvider = Depends(get_news_provider),
    logger: ILoggingProvider = Depends(get_logger),
    config: AppConfig = Depends(get_settings),
) -> NewsFeed:
    return NewsFeed(
        news_provider=news_provider,
        logger=logger,
        config=config,
    )


def get_technical_filter_use_case(
    config: AppConfig = Depends(get_settings),
    logger: ILoggingProvider = Depends(get_logger),
) -> TechnicalFilter:
    return TechnicalFilter(
        config=config,
        logger=logger,
    )


def get_ai_analyser_use_case(
    ai_provider: IAiProvider = Depends(get_ai_provider),
    knowledge_repository: IKnowledgeRepository = Depends(get_knowledge_repository),
    config: AppConfig = Depends(get_settings),
    logger: ILoggingProvider = Depends(get_logger),
) -> AiAnalyser:
    return AiAnalyser(
        ai_provider=ai_provider,
        knowledge_repository=knowledge_repository,
        config=config,
        logger=logger,
    )


def get_account_loader_use_case(
    execution_provider: IExecutionProvider = Depends(get_execution_provider),
    stock_provider: IStockProvider = Depends(get_stock_provider),
    logger: ILoggingProvider = Depends(get_logger),
) -> AccountLoader:
    return AccountLoader(
        execution_provider=execution_provider,
        stock_provider=stock_provider,
        logger=logger,
    )


def get_account_risk_check_use_case(
    price_provider: IOhlcvProvider = Depends(get_price_provider),
    config: AppConfig = Depends(get_settings),
    logger: ILoggingProvider = Depends(get_logger),
) -> AccountRiskCheck:
    return AccountRiskCheck(
        price_provider=price_provider,
        config=config,
        logger=logger,
    )


def get_signals_use_case(
    signal_repository: ISignalRepository = Depends(get_signal_repository),
    knowledge_repository: IKnowledgeRepository = Depends(get_knowledge_repository),
    config: AppConfig = Depends(get_settings),
    logger: ILoggingProvider = Depends(get_logger),
) -> Signals:
    return Signals(
        signal_repository=signal_repository,
        knowledge_repository=knowledge_repository,
        config=config,
        logger=logger,
    )


def get_order_execution_use_case(
    execution_provider: IExecutionProvider = Depends(get_execution_provider),
    market_clock: IMarketClock = Depends(get_market_clock),
    logger: ILoggingProvider = Depends(get_logger),
) -> OrderExecution:
    return OrderExecution(
        execution_provider=execution_provider,
        market_clock=market_clock,
        logger=logger,
    )


def get_reporting_use_case(
    notification_provider: INotificationProvider | None = Depends(get_notification_provider),
    config: AppConfig = Depends(get_settings),
    logger: ILoggingProvider = Depends(get_logger),
) -> Reporting:
    return Reporting(
        notification_provider=notification_provider,
        config=config,
        logger=logger,
    )


def get_analysis_pipeline_use_case(
    news_feed: NewsFeed = Depends(get_news_feed_use_case),
    ai_analyser: AiAnalyser = Depends(get_ai_analyser_use_case),
    logger: ILoggingProvider = Depends(get_logger),
) -> AnalysisPipeline:
    return AnalysisPipeline(
        news_feed=news_feed,
        ai_analyser=ai_analyser,
        logger=logger,
    )


def get_trading_workflow_use_case(
    market_scanner: MarketScanner = Depends(get_market_scanner_use_case),
    buzz_scanner: BuzzScanner = Depends(get_buzz_scanner_use_case),
    stock_provider: IStockProvider = Depends(get_stock_provider),
    watchlist_repository: IWatchlistRepository = Depends(get_watchlist_repository),
    account_loader: AccountLoader = Depends(get_account_loader_use_case),
    account_risk_check: AccountRiskCheck = Depends(get_account_risk_check_use_case),
    technical_filter: TechnicalFilter = Depends(get_technical_filter_use_case),
    analysis_pipeline: AnalysisPipeline = Depends(get_analysis_pipeline_use_case),
    signals: Signals = Depends(get_signals_use_case),
    order_execution: OrderExecution = Depends(get_order_execution_use_case),
    reporting: Reporting = Depends(get_reporting_use_case),
    logger: ILoggingProvider = Depends(get_logger),
) -> TradingWorkflow:
    return TradingWorkflow(
        market_scanner=market_scanner,
        buzz_scanner=buzz_scanner,
        stock_provider=stock_provider,
        watchlist_repository=watchlist_repository,
        account_loader=account_loader,
        account_risk_check=account_risk_check,
        technical_filter=technical_filter,
        analysis_pipeline=analysis_pipeline,
        signals=signals,
        order_execution=order_execution,
        reporting=reporting,
        logger=logger,
    )
