from a_domain.model.valuation.scan import MarketValuation, ValuationScan


class LoadMarket:
    async def execute(self, scan: ValuationScan) -> MarketValuation:
        return MarketValuation(prices=dict.fromkeys(scan.survivors, 0.0))
