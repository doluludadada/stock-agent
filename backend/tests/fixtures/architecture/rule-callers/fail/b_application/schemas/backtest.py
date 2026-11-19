from dataclasses import dataclass, field

from a_domain.rules.technical.strategy import TechnicalStrategy


@dataclass(frozen=True)
class BacktestSetup:
    strategy: TechnicalStrategy = field(default_factory=TechnicalStrategy)
