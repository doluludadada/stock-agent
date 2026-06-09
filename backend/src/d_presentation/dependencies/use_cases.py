# backend/src/d_presentation/dependencies/use_cases.py

from fastapi import Depends

from a_domain.ports.ai.ai_provider import IAiProvider
from a_domain.ports.ai.knowledge_repository import IKnowledgeRepository
from a_domain.ports.analysis.indicator_provider import IIndicatorProvider
from a_domain.ports.market.news_provider import INewsProvider
from a_domain.ports.market.price_provider import IPriceProvider
from a_domain.ports.market.stock_provider import IStockProvider
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.system.market_clock import IMarketClock
from a_domain.ports.system.notification_provider import INotificationProvider
from a_domain.ports.trading.execution_provider import IExecutionProvider
from a_domain.ports.trading.signal_repository import ISignalRepository
from a_domain.ports.trading.watchlist_repository import IWatchlistRepository
from b_application.pipeline import Pipeline
from b_application.schemas.config import AppConfig
from b_application.use_cases.collect.market_data import MarketData
from b_application.use_cases.collect.buzz_scanner import BuzzScanner
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
from d_presentation.dependencies.core import (
    get_logger,
    get_market_clock,
    get_notification_provider,
    get_settings,
)
from d_presentation.dependencies.providers import (
    get_indicator_provider,
    get_news_provider,
    get_price_provider,
    get_stock_provider,
)
from d_presentation.dependencies.repositories import (
    get_ai_provider,
    get_execution_provider,
    get_knowledge_repository,
    get_signal_repository,
    get_watchlist_repository,
)


def get_watchlist_use_case(
    stock_provider: IStockProvider = Depends(get_stock_provider),
    price_provider: IPriceProvider = Depends(get_price_provider),
    indicator_provider: IIndicatorProvider = Depends(get_indicator_provider),
    watchlist_repo: IWatchlistRepository = Depends(get_watchlist_repository),
    logger: ILoggingProvider = Depends(get_logger),
    config: AppConfig = Depends(get_settings),
    market_clock: IMarketClock = Depends(get_market_clock),
) -> Watchlist:
    return Watchlist(
        stock_provider=stock_provider,
        price_provider=price_provider,
        indicator_provider=indicator_provider,
        watchlist_repo=watchlist_repo,
        logger=logger,
        config=config,
        market_clock=market_clock,
    )


def get_market_scan_use_case(
    social_media_provider,
    watchlist_repo: IWatchlistRepository = Depends(get_watchlist_repository),
    stock_provider: IStockProvider = Depends(get_stock_provider),
    logger: ILoggingProvider = Depends(get_logger),
    config: AppConfig = Depends(get_settings),
) -> BuzzScanner:
    return BuzzScanner(
        social_media_provider=social_media_provider,
        watchlist_repo=watchlist_repo,
        stock_provider=stock_provider,
        logger=logger,
        config=config,
    )


def get_stock_selector_use_case(
    watchlist_repo: IWatchlistRepository = Depends(get_watchlist_repository),
    stock_provider: IStockProvider = Depends(get_stock_provider),
    logger: ILoggingProvider = Depends(get_logger),
) -> StockSelector:
    return StockSelector(
        watchlist_repo=watchlist_repo,
        stock_provider=stock_provider,
        logger=logger,
    )


def get_market_data_use_case(
    price_provider: IPriceProvider = Depends(get_price_provider),
    logger: ILoggingProvider = Depends(get_logger),
    config: AppConfig = Depends(get_settings),
    market_clock: IMarketClock = Depends(get_market_clock),
) -> MarketData:
    return MarketData(
        price_provider=price_provider,
        logger=logger,
        config=config,
        market_clock=market_clock,
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
    indicator_provider: IIndicatorProvider = Depends(get_indicator_provider),
    config: AppConfig = Depends(get_settings),
    logger: ILoggingProvider = Depends(get_logger),
) -> TechnicalFilter:
    return TechnicalFilter(
        indicator_provider=indicator_provider,
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
        knowledge_repo=knowledge_repository,
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
    price_provider: IPriceProvider = Depends(get_price_provider),
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
    logger: ILoggingProvider = Depends(get_logger),
) -> OrderExecution:
    return OrderExecution(
        execution_provider=execution_provider,
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


def get_pipeline(
    account_loader: AccountLoader = Depends(get_account_loader_use_case),
    account_risk_check: AccountRiskCheck = Depends(get_account_risk_check_use_case),
    stock_selector: StockSelector = Depends(get_stock_selector_use_case),
    market_data: MarketData = Depends(get_market_data_use_case),
    technical_filter: TechnicalFilter = Depends(get_technical_filter_use_case),
    news_feed: NewsFeed = Depends(get_news_feed_use_case),
    ai_analyser: AiAnalyser = Depends(get_ai_analyser_use_case),
    signals: Signals = Depends(get_signals_use_case),
    order_execution: OrderExecution = Depends(get_order_execution_use_case),
    reporting: Reporting = Depends(get_reporting_use_case),
    logger: ILoggingProvider = Depends(get_logger),
) -> Pipeline:
    return Pipeline(
        account_loader=account_loader,
        account_risk_check=account_risk_check,
        stock_selector=stock_selector,
        market_data=market_data,
        technical_filter=technical_filter,
        news_feed=news_feed,
        ai_analyser=ai_analyser,
        signals=signals,
        order_execution=order_execution,
        reporting=reporting,
        logger=logger,
    )
