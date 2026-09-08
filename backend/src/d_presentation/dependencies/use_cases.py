# backend/src/d_presentation/dependencies/use_cases.py

from typing import Annotated

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
from b_application.factories.technical_strategy import create_technical_strategies
from b_application.pipeline import Pipeline
from b_application.schemas.config import AppConfig
from b_application.schemas.technical_strategies import TechnicalStrategies
from b_application.use_cases.collect.buzz_scanner import BuzzScanner
from b_application.use_cases.collect.market_data_collector import MarketDataCollector
from b_application.use_cases.collect.market_scanner import MarketScanner
from b_application.use_cases.collect.news_feed import NewsFeed
from b_application.use_cases.process.ai_analyser import AiAnalyser
from b_application.use_cases.process.composite_scorer import CompositeScorer
from b_application.use_cases.process.technical_filter import TechnicalFilter
from b_application.use_cases.ship.reporting import Reporting
from b_application.use_cases.ship.signals import Signals
from b_application.use_cases.trade.account_loader import AccountLoader
from b_application.use_cases.trade.account_risk_check import AccountRiskCheck
from b_application.use_cases.trade.order_execution import OrderExecution
from b_application.use_cases.trade.watch_stocks import WatchStocks
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
    stock_provider: Annotated[
        IStockProvider,
        Depends(get_stock_provider),
    ],
    watchlist_repository: Annotated[
        IWatchlistRepository,
        Depends(get_watchlist_repository),
    ],
    logger: Annotated[
        ILoggingProvider,
        Depends(get_logger),
    ],
) -> MarketScanner:
    return MarketScanner(
        stock_provider=stock_provider,
        watchlist_repository=watchlist_repository,
        logger=logger,
    )


def get_market_data_collector_use_case(
    price_provider: Annotated[
        IOhlcvProvider,
        Depends(get_price_provider),
    ],
    market_clock: Annotated[
        IMarketClock,
        Depends(get_market_clock),
    ],
    config: Annotated[
        AppConfig,
        Depends(get_settings),
    ],
    logger: Annotated[
        ILoggingProvider,
        Depends(get_logger),
    ],
) -> MarketDataCollector:
    return MarketDataCollector(
        ohlcv_provider=price_provider,
        market_clock=market_clock,
        config=config,
        logger=logger,
    )


def get_buzz_scanner_use_case(
    social_media_provider: Annotated[
        ISocialMediaProvider,
        Depends(get_social_media_provider),
    ],
    stock_provider: Annotated[
        IStockProvider,
        Depends(get_stock_provider),
    ],
    logger: Annotated[
        ILoggingProvider,
        Depends(get_logger),
    ],
    config: Annotated[
        AppConfig,
        Depends(get_settings),
    ],
) -> BuzzScanner:
    return BuzzScanner(
        social_media_provider=social_media_provider,
        stock_provider=stock_provider,
        logger=logger,
        config=config,
    )


def get_news_feed_use_case(
    news_provider: Annotated[
        INewsProvider,
        Depends(get_news_provider),
    ],
    logger: Annotated[
        ILoggingProvider,
        Depends(get_logger),
    ],
    config: Annotated[
        AppConfig,
        Depends(get_settings),
    ],
) -> NewsFeed:
    return NewsFeed(
        news_provider=news_provider,
        logger=logger,
        config=config,
    )


def get_technical_filter_use_case(
    logger: Annotated[
        ILoggingProvider,
        Depends(get_logger),
    ],
) -> TechnicalFilter:
    return TechnicalFilter(
        logger=logger,
    )


def get_technical_strategies(
    config: Annotated[
        AppConfig,
        Depends(get_settings),
    ],
) -> TechnicalStrategies:
    return create_technical_strategies(
        config,
    )


def get_ai_analyser_use_case(
    ai_provider: Annotated[
        IAiProvider,
        Depends(get_ai_provider),
    ],
    knowledge_repository: Annotated[
        IKnowledgeRepository,
        Depends(get_knowledge_repository),
    ],
    config: Annotated[
        AppConfig,
        Depends(get_settings),
    ],
    logger: Annotated[
        ILoggingProvider,
        Depends(get_logger),
    ],
) -> AiAnalyser:
    return AiAnalyser(
        ai_provider=ai_provider,
        knowledge_repository=knowledge_repository,
        config=config,
        logger=logger,
    )


def get_composite_scorer_use_case(
    config: Annotated[
        AppConfig,
        Depends(get_settings),
    ],
    logger: Annotated[
        ILoggingProvider,
        Depends(get_logger),
    ],
) -> CompositeScorer:
    return CompositeScorer(
        config=config,
        logger=logger,
    )


def get_account_loader_use_case(
    execution_provider: Annotated[
        IExecutionProvider,
        Depends(get_execution_provider),
    ],
    stock_provider: Annotated[
        IStockProvider,
        Depends(get_stock_provider),
    ],
    logger: Annotated[
        ILoggingProvider,
        Depends(get_logger),
    ],
) -> AccountLoader:
    return AccountLoader(
        execution_provider=execution_provider,
        stock_provider=stock_provider,
        logger=logger,
    )


def get_account_risk_check_use_case(
    price_provider: Annotated[
        IOhlcvProvider,
        Depends(get_price_provider),
    ],
    config: Annotated[
        AppConfig,
        Depends(get_settings),
    ],
    logger: Annotated[
        ILoggingProvider,
        Depends(get_logger),
    ],
) -> AccountRiskCheck:
    return AccountRiskCheck(
        price_provider=price_provider,
        config=config,
        logger=logger,
    )


def get_signals_use_case(
    signal_repository: Annotated[
        ISignalRepository,
        Depends(get_signal_repository),
    ],
    config: Annotated[
        AppConfig,
        Depends(get_settings),
    ],
    logger: Annotated[
        ILoggingProvider,
        Depends(get_logger),
    ],
) -> Signals:
    return Signals(
        signal_repository=signal_repository,
        config=config,
        logger=logger,
    )


def get_order_execution_use_case(
    execution_provider: Annotated[
        IExecutionProvider,
        Depends(get_execution_provider),
    ],
    market_clock: Annotated[
        IMarketClock,
        Depends(get_market_clock),
    ],
    logger: Annotated[
        ILoggingProvider,
        Depends(get_logger),
    ],
) -> OrderExecution:
    return OrderExecution(
        execution_provider=execution_provider,
        market_clock=market_clock,
        logger=logger,
    )


def get_reporting_use_case(
    notification_provider: Annotated[
        INotificationProvider | None,
        Depends(get_notification_provider),
    ],
    config: Annotated[
        AppConfig,
        Depends(get_settings),
    ],
    logger: Annotated[
        ILoggingProvider,
        Depends(get_logger),
    ],
) -> Reporting:
    return Reporting(
        notification_provider=notification_provider,
        config=config,
        logger=logger,
    )


def get_watch_stocks_use_case(
    watchlist_repository: Annotated[
        IWatchlistRepository,
        Depends(get_watchlist_repository),
    ],
    logger: Annotated[
        ILoggingProvider,
        Depends(get_logger),
    ],
) -> WatchStocks:
    return WatchStocks(
        watchlist_repository=watchlist_repository,
        logger=logger,
    )


def get_pipeline(
    account_loader: Annotated[
        AccountLoader,
        Depends(get_account_loader_use_case),
    ],
    account_risk_check: Annotated[
        AccountRiskCheck,
        Depends(get_account_risk_check_use_case),
    ],
    market_scanner: Annotated[
        MarketScanner,
        Depends(get_market_scanner_use_case),
    ],
    data_collector: Annotated[
        MarketDataCollector,
        Depends(get_market_data_collector_use_case),
    ],
    buzz_scanner: Annotated[
        BuzzScanner,
        Depends(get_buzz_scanner_use_case),
    ],
    news: Annotated[
        NewsFeed,
        Depends(get_news_feed_use_case),
    ],
    ai: Annotated[
        AiAnalyser,
        Depends(get_ai_analyser_use_case),
    ],
    technical_filter: Annotated[
        TechnicalFilter,
        Depends(get_technical_filter_use_case),
    ],
    technical_strategies: Annotated[
        TechnicalStrategies,
        Depends(get_technical_strategies),
    ],
    composite_scorer: Annotated[
        CompositeScorer,
        Depends(get_composite_scorer_use_case),
    ],
    signals: Annotated[
        Signals,
        Depends(get_signals_use_case),
    ],
    order_execution: Annotated[
        OrderExecution,
        Depends(get_order_execution_use_case),
    ],
    reporting: Annotated[
        Reporting,
        Depends(get_reporting_use_case),
    ],
    watch_stocks: Annotated[
        WatchStocks,
        Depends(get_watch_stocks_use_case),
    ],
    logger: Annotated[
        ILoggingProvider,
        Depends(get_logger),
    ],
) -> Pipeline:
    return Pipeline(
        account_loader=account_loader,
        account_risk_check=account_risk_check,
        market_scanner=market_scanner,
        data_collector=data_collector,
        buzz_scanner=buzz_scanner,
        news=news,
        ai=ai,
        technical_filter=technical_filter,
        technical_strategies=technical_strategies,
        composite_scorer=composite_scorer,
        signals=signals,
        order_execution=order_execution,
        reporting=reporting,
        watch_stocks=watch_stocks,
        logger=logger,
    )
