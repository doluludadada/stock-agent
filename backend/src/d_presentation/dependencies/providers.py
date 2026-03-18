from functools import lru_cache

from fastapi import Depends

from a_domain.ports.analysis.indicator_provider import IIndicatorProvider
from a_domain.ports.chat.web_search_provider import IWebSearchProvider
from a_domain.ports.market.news_provider import INewsProvider
from a_domain.ports.market.price_provider import IPriceProvider
from a_domain.ports.market.stock_provider import IStockProvider
from a_domain.ports.system.logging_provider import ILoggingProvider
from b_application.schemas.config import AppConfig
from c_infrastructure.feed.news_provider import NewsProvider
from c_infrastructure.feed.tavily_provider import TavilySearchAdapter
from c_infrastructure.market.indicator_provider import IndicatorProvider
from c_infrastructure.market.twse_provider import TaiwanStockProvider
from c_infrastructure.market.yahoo_finance_adapter import YahooFinanceProvider
from d_presentation.dependencies.core import get_logger, get_settings


@lru_cache
def get_indicator_provider(config: AppConfig = Depends(get_settings)) -> IIndicatorProvider:
    return IndicatorProvider(config=config)


@lru_cache
def get_tavily_search(config: AppConfig = Depends(get_settings), logger: ILoggingProvider = Depends(get_logger)) -> IWebSearchProvider:
    return TavilySearchAdapter(config=config, logger=logger)


@lru_cache
def get_price_provider(logger: ILoggingProvider = Depends(get_logger)) -> IPriceProvider:
    return YahooFinanceProvider(logger=logger)


@lru_cache
def get_stock_provider(logger: ILoggingProvider = Depends(get_logger)) -> IStockProvider:
    return TaiwanStockProvider(logger=logger)


@lru_cache
def get_news_provider(config: AppConfig = Depends(get_settings), logger: ILoggingProvider = Depends(get_logger)) -> INewsProvider:
    return NewsProvider(config=config, logger=logger)
