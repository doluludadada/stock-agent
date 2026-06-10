# backend/src/d_presentation/dependencies/providers.py

from functools import lru_cache

from fastapi import Depends

from a_domain.ports.chat.web_search_provider import IWebSearchProvider
from a_domain.ports.market.news_provider import INewsProvider
from a_domain.ports.market.price_provider import IOhlcvProvider
from a_domain.ports.market.social_media_provider import ISocialMediaProvider
from a_domain.ports.market.stock_provider import IStockProvider
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.system.market_clock import IMarketClock
from b_application.schemas.config import AppConfig
from c_infrastructure.database.db_connector import DatabaseConnector
from c_infrastructure.feed.news_provider import NewsProvider
from c_infrastructure.feed.ptt_provider import PttProvider
from c_infrastructure.feed.tavily_provider import TavilySearchAdapter
from c_infrastructure.market.cached_price_provider import CachedPriceProvider
from c_infrastructure.market.twse_provider import TaiwanStockProvider
from c_infrastructure.market.yahoo_finance_adapter import YahooFinanceProvider
from d_presentation.dependencies.core import get_db_connector, get_logger, get_market_clock, get_settings


@lru_cache
def get_tavily_search(
    config: AppConfig = Depends(get_settings),
    logger: ILoggingProvider = Depends(get_logger),
) -> IWebSearchProvider | None:
    if not config.tavily.api_key:
        return None

    return TavilySearchAdapter(config=config, logger=logger)


@lru_cache
def get_raw_price_provider(logger: ILoggingProvider = Depends(get_logger)) -> IOhlcvProvider:
    return YahooFinanceProvider(logger=logger)


@lru_cache
def get_price_provider(
    logger: ILoggingProvider = Depends(get_logger),
    db: DatabaseConnector = Depends(get_db_connector),
    market_clock: IMarketClock = Depends(get_market_clock),
) -> IOhlcvProvider:
    return CachedPriceProvider(
        price_provider=YahooFinanceProvider(logger=logger),
        db=db,
        logger=logger,
        market_clock=market_clock,
    )


@lru_cache
def get_stock_provider(logger: ILoggingProvider = Depends(get_logger)) -> IStockProvider:
    return TaiwanStockProvider(logger=logger)


@lru_cache
def get_news_provider(
    config: AppConfig = Depends(get_settings),
    logger: ILoggingProvider = Depends(get_logger),
) -> INewsProvider:
    return NewsProvider(config=config, logger=logger)


@lru_cache
def get_social_media_provider(
    config: AppConfig = Depends(get_settings),
    logger: ILoggingProvider = Depends(get_logger),
    stock_provider: IStockProvider = Depends(get_stock_provider),
) -> ISocialMediaProvider:
    return PttProvider(
        config=config,
        logger=logger,
        stock_provider=stock_provider,
    )
