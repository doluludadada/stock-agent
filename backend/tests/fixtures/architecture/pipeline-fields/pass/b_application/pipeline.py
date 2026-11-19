from dataclasses import dataclass

from a_domain.ports.market import IStockProvider
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.trading.backtest_repository import IBacktestRepository
from b_application.use_cases.collect import scan


@dataclass
class Pipeline:
    scanner: scan.MarketScanner
    stock_provider: IStockProvider
    backtest_repository: IBacktestRepository
    logger: ILoggingProvider
