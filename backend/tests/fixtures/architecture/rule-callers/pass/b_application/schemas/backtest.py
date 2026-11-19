from dataclasses import dataclass

from a_domain.rules.technical.strategy import TechnicalStrategy


@dataclass(frozen=True)
class BacktestSetup:
    strategy: TechnicalStrategy
    first_day: str | None
