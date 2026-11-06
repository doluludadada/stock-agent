from a_domain.model.market.stock import Stock
from a_domain.model.system.stats import SystemStats
from a_domain.ports.market.fundamentals_provider import IFundamentalsProvider
from a_domain.ports.market.taiwan_stock_provider import ITaiwanStockProvider
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.system.market_clock import IMarketClock
from a_domain.rules.fundamentals.filing import FilingWarningRule
from a_domain.rules.fundamentals.trailing_eps import TrailingEpsQuartersRule, TrailingEpsRule
from a_domain.types.errors import MopsUnavailable


class FundamentalsFeed:
    """
    Sets stock.eps (TTM from official filings) and stock.industry.

    It is the only writer of Stock.eps. Without a fundamentals provider, on an audience that reads no MOPS (public), it
    raises MopsUnavailable; the Web API and the CLI refuse the valuation before it gets here.
    """

    def __init__(
        self,
        fundamentals_provider: IFundamentalsProvider | None,
        stock_provider: ITaiwanStockProvider,
        market_clock: IMarketClock,
        logger: ILoggingProvider,
    ) -> None:
        self._fundamentals_provider = fundamentals_provider
        self._stock_provider = stock_provider
        self._market_clock = market_clock
        self._logger = logger
        self._trailing_eps_quarters = TrailingEpsQuartersRule()
        self._trailing_eps = TrailingEpsRule()
        self._filing_warnings = FilingWarningRule()

    async def execute(self, stocks: list[Stock], stats: SystemStats) -> None:
        if self._fundamentals_provider is None:
            raise MopsUnavailable("This site uses open data only and reads no MOPS income statement, so it values no stock.")

        if not stocks:
            return

        today = self._market_clock.today()
        quarters = self._trailing_eps_quarters.apply(today)
        filings = await self._fundamentals_provider.fetch_cumulative_eps(quarters)
        industries = await self._stock_provider.fetch_industries()

        for warning in self._filing_warnings.apply(filings):
            self._logger.warning(warning)
            stats.add_error(warning)

        for stock in stocks:
            stock.eps = self._trailing_eps.apply(stock.stock_id, filings, today)
            stock.industry = industries.get(stock.stock_id, stock.industry)

        self._logger.info(f"Fundamentals loaded for {len(stocks)} stocks. Quarters={sorted(map(str, quarters))}.")
