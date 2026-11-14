from typing import Literal, overload

from a_domain.model.fundamentals.monthly_revenue import MonthlyRevenue
from a_domain.model.fundamentals.quarter_financials import QuarterFinancials
from a_domain.ports.market.daily_close_archive import IDailyCloseArchive
from a_domain.ports.market.fundamentals_provider import IFundamentalsProvider
from a_domain.ports.system.market_clock import IMarketClock
from a_domain.rules.fundamentals.stock_analysis import EarningsTrendRule, StockAnalysis, StockAnalysisRule
from a_domain.rules.fundamentals.trailing_eps import QuarterEps, filing_candidates
from a_domain.types.enums import MarketType
from b_application.config.app_config import AppConfig


class StockAnalysisLookup:
    """
    One stock's financials for its page, from held data alone: each quarter's figures and each month's revenue as the
    open-data archive holds them, oldest first, and their analysis (StockAnalysisRule), which also reads the archive's
    valuation ratios and the year-to-date EPS of the latest stock_page.eps_quarters quarters in the MOPS pages the
    site already holds. It fetches nothing. `mops` is None on a site that reads no MOPS (public), whose analysis
    reads the archive alone. Without `with_analysis` it reads the quarters and the revenue alone, and the analysis is
    None.
    """

    def __init__(
        self, archive: IDailyCloseArchive, mops: IFundamentalsProvider | None, market_clock: IMarketClock, config: AppConfig
    ) -> None:
        self._archive = archive
        self._mops = mops
        self._market_clock = market_clock
        self._eps_quarters = config.stock_page.eps_quarters
        self._analysis_rule = StockAnalysisRule(
            revenue_rule=config.ranking.revenue_trend_rule(),
            earnings_rule=EarningsTrendRule(),
            valuation_rule=config.stock_page.valuation_rule(),
        )

    @overload
    async def execute(self, stock_id: str) -> tuple[list[QuarterFinancials], list[MonthlyRevenue], StockAnalysis]: ...

    @overload
    async def execute(
        self, stock_id: str, *, with_analysis: Literal[False]
    ) -> tuple[list[QuarterFinancials], list[MonthlyRevenue], None]: ...

    async def execute(
        self, stock_id: str, *, with_analysis: bool = True
    ) -> tuple[list[QuarterFinancials], list[MonthlyRevenue], StockAnalysis | None]:
        quarters, revenues = await self._archive.financials(stock_id)

        if not with_analysis:
            return quarters, revenues, None

        ratios = await self._archive.valuation_history(stock_id)
        pages: list[QuarterEps] = []
        quarter = filing_candidates(self._market_clock.today())[0]

        for _ in range(self._eps_quarters):
            if self._mops is None:
                break

            held = [await self._mops.load_page(market, quarter) for market in MarketType]
            pages += [page for page in held if page is not None]
            quarter = quarter.previous()

        return quarters, revenues, self._analysis_rule.apply(stock_id, quarters, revenues, pages, ratios)
