from dataclasses import dataclass

from a_domain.ports.system.logging_provider import ILoggingProvider
from b_application.use_cases.collect import scan


@dataclass
class Pipeline:
    scanner: scan.MarketScanner
    logger: ILoggingProvider
