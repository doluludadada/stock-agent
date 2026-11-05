from a_domain.rules.trading.sizing import SizingRule
from a_domain.rules.trading.cost import TradeCost
from a_domain.rules.trading.exit import StopLossRule
from a_domain.rules.technical.strategy import TechnicalSettings, TechnicalStrategy
from a_domain.rules.collect.freshness import DataFreshnessRule
import a_domain.rules.trading.tick


class Pipeline:
    async def size(self, total: int) -> SizingRule:
        return SizingRule(lot=total)

    async def fee(self, price: float) -> float:
        return TradeCost.fee_rate * price

    async def stop(self, rule: object) -> bool:
        return isinstance(rule, StopLossRule)

    async def save(self, settings: TechnicalSettings) -> TechnicalSettings:
        default = TechnicalStrategy
        return settings or default

    async def tick(self, price: a_domain.rules.trading.tick.Tick) -> float:
        return price
