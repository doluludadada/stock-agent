from pydantic.dataclasses import dataclass

from a_domain.model.valuation.scan import MarketValuation, ValuationScan


@dataclass(frozen=True)
class ValuationScreenRule:
    max_price: float

    def apply(self, market: MarketValuation) -> ValuationScan:
        return ValuationScan(survivors=tuple(stock_id for stock_id, price in market.prices.items() if price <= self.max_price))
