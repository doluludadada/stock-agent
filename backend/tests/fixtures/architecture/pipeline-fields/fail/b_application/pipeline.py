from dataclasses import dataclass

from a_domain.ports.chat.web_search_provider import WebSearchResult
from a_domain.ports.market.stock_provider import IStockProvider
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.trading import IExecutionProvider
from a_domain.ports.trading.paper_execution_provider import IPaperExecutionProvider
from b_application.use_cases.collect.scan import MarketScanner


@dataclass
class CollectSteps:
    scanner: MarketScanner


@dataclass
class Pipeline:
    collect: CollectSteps
    scanner: MarketScanner
    stock_provider: IStockProvider
    execution_provider: IExecutionProvider
    paper_execution_provider: IPaperExecutionProvider
    last_search: WebSearchResult
    reset_commands: frozenset[str]
    logger: ILoggingProvider
