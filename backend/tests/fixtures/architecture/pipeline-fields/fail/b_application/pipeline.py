from dataclasses import dataclass

from a_domain.ports.market.stock_provider import IStockProvider
from a_domain.ports.system.logging_provider import ILoggingProvider
from b_application.use_cases.collect.scan import MarketScanner


@dataclass
class CollectSteps:
    scanner: MarketScanner


@dataclass
class Pipeline:
    collect: CollectSteps
    scanner: MarketScanner
    stock_provider: IStockProvider
    reset_commands: frozenset[str]
    logger: ILoggingProvider
