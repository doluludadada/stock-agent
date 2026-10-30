from a_domain.model.market.stock import Stock
from a_domain.ports.market.fundamentals_provider import IFundamentalsProvider
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.system.market_clock import IMarketClock
from a_domain.rules.fundamentals.trailing_eps import TrailingEpsRule
from b_application.schemas.pipeline_status import PipelineStatus


class FundamentalsFeed:
    """
    Sets stock.eps (TTM from official filings) and stock.industry.

    It is the only writer of Stock.eps.
    """

    def __init__(self, fundamentals_provider: IFundamentalsProvider, market_clock: IMarketClock, logger: ILoggingProvider) -> None:
        self._fundamentals_provider = fundamentals_provider
        self._market_clock = market_clock
        self._logger = logger

    async def execute(self, stocks: list[Stock], status: PipelineStatus) -> None:
        if not stocks:
            return

        rule = TrailingEpsRule.as_of(self._market_clock.today())
        filings = await self._fundamentals_provider.fetch_cumulative_eps(rule.required_quarters)
        industries = await self._fundamentals_provider.fetch_industries()

        for quarter in sorted(quarter for quarter, filing in filings.items() if filing is None):
            message = f"MOPS {quarter} 財報資料取得失敗，需要此季的股票 EPS 將標示為資料不足或非最新"
            self._logger.warning(message)
            status.stats.add_error(message)

        for stock in stocks:
            stock.eps = rule.evaluate(stock.stock_id, filings)
            stock.industry = industries.get(stock.stock_id, stock.industry)

        self._logger.info(f"Fundamentals loaded for {len(stocks)} stocks. Quarters={sorted(map(str, rule.required_quarters))}.")
