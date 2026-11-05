from a_domain.model.market.stock import Stock
from a_domain.model.system.stats import SystemStats
from a_domain.model.valuation.scan import MarketValuation
from a_domain.ports.market.stock_provider import IStockProvider
from a_domain.ports.system.market_clock import IMarketClock
from a_domain.rules.fundamentals.filing import FilingDeadlineRule
from a_domain.rules.valuation.valuation import StockValuationRule
from b_application.config.app_config import AppConfig


class MarketValuationLoader:
    """Use Case: values every listed and OTC stock at the exchanges' latest official close, before any user assumption."""

    def __init__(self, stock_provider: IStockProvider, market_clock: IMarketClock, config: AppConfig) -> None:
        self._stock_provider = stock_provider
        self._market_clock = market_clock
        self._stock_valuation_rule = StockValuationRule(
            max_missed_sessions=config.freshness.daily_close_max_missed_sessions,
            filing_deadline_rule=FilingDeadlineRule(config.sources.mops.filing_deadlines),
        )

    async def execute(self, stocks: list[Stock], stats: SystemStats) -> MarketValuation:
        """The stocks carry their EPS already. The run errors so far, such as a MOPS quarter that failed, become source warnings."""
        closes = await self._stock_provider.get_latest_closes()
        last_closed_session = self._market_clock.last_closed_session()

        return MarketValuation(
            valuations={
                stock.stock_id: self._stock_valuation_rule.apply(stock, closes.get(stock.stock_id), last_closed_session)
                for stock in stocks
            },
            last_closed_session=last_closed_session,
            source_warnings=tuple(stats.errors),
        ).with_industry_medians()
