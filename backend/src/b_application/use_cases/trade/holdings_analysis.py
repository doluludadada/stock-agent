from collections.abc import Mapping, Sequence

from a_domain.model.trading.account import Position
from a_domain.ports.market.daily_close_archive import IDailyCloseArchive
from a_domain.ports.market.stock_provider import IStockProvider
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.system.market_clock import IMarketClock
from a_domain.rules.trading.holdings import LastCloseRule, PortfolioAnalysis, PortfolioAnalysisRule
from a_domain.rules.trading.ranking import RankingHistory
from a_domain.rules.trading.ranking_standing import RankingStanding
from a_domain.types.enums import HoldingSource
from b_application.config.app_config import AppConfig


class HoldingsAnalysis:
    """
    Use Case: Read the holdings as one portfolio from held data alone (PortfolioAnalysisRule): each stock's last close
    in the ranking's daily history, its name in the listing, its standing in the monthly ranking as `standings` holds
    it, and its revenue trend from the archived months by the stock page's own rule. It fetches no price. A listing
    outage leaves the holdings unnamed.
    """

    def __init__(
        self,
        stock_provider: IStockProvider,
        archive: IDailyCloseArchive,
        market_clock: IMarketClock,
        config: AppConfig,
        logger: ILoggingProvider,
    ) -> None:
        self._stock_provider = stock_provider
        self._archive = archive
        self._market_clock = market_clock
        self._last_close_rule = LastCloseRule()
        self._revenue_rule = config.ranking.revenue_trend_rule()
        self._analysis_rule = PortfolioAnalysisRule(
            position_value_rule=config.market.position_value_rule(), concentration_positions=config.holdings.concentration_positions
        )
        self._logger = logger

    async def execute(
        self, held: Mapping[HoldingSource, Sequence[Position]], history: RankingHistory, standings: Mapping[str, RankingStanding]
    ) -> PortfolioAnalysis:
        stock_ids = sorted({position.stock_id for positions in held.values() for position in positions})
        found = {stock_id: self._last_close_rule.apply(history.bars, stock_id) for stock_id in stock_ids}
        closes = {
            stock_id: (close[0], self._market_clock.session_close(close[1])) for stock_id, close in found.items() if close is not None
        }
        names: dict[str, str] = {}

        try:
            listed = [await self._stock_provider.get_by_id(stock_id) for stock_id in stock_ids]
            names = {stock.stock_id: stock.name for stock in listed if stock is not None and stock.name is not None}
        except Exception as error:
            self._logger.warning(f"Holdings: the listing is unavailable, so the holdings are unnamed: {error}")

        months = {stock_id: (await self._archive.financials(stock_id))[1] for stock_id in stock_ids}
        revenues = {stock_id: self._revenue_rule.apply(held_months) for stock_id, held_months in months.items() if held_months}

        return self._analysis_rule.apply(held, closes, names, standings, revenues)
