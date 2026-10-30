from dataclasses import dataclass

from a_domain.model.chat.message import Message
from a_domain.model.system.stats import SystemStats
from a_domain.model.valuation.scan import MarketValuation, ValuationScan
from a_domain.model.valuation.valuation import ValuationExplanation, ValuationReport
from a_domain.ports.ai.ai_provider import IAiProvider
from a_domain.ports.analysis.technical_settings_repository import ITechnicalSettingsRepository
from a_domain.ports.market.stock_provider import IStockProvider
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.system.market_clock import IMarketClock
from a_domain.rules.ai.parser import parse_valuation_explanation
from a_domain.rules.ai.prompt import ValuationPromptBuilder
from a_domain.types.enums import ExecutionProvider, MessageRole, OrderMode, Workflow
from b_application.schemas.pipeline_status import PipelineStatus
from b_application.use_cases.collect.fundamentals_feed import FundamentalsFeed
from b_application.use_cases.collect.market_data_collector import MarketDataCollector
from b_application.use_cases.collect.news_feed import NewsFeed
from b_application.use_cases.process.technical_filter import TechnicalFilter


def valuation_status() -> PipelineStatus:
    """
    Collects one valuation step's counters and errors for the shared collect and process use cases.
    Valuation records no run and sends no order, so the run identity is fixed to values that cannot order.
    """
    return PipelineStatus(
        stats=SystemStats(workflow=Workflow.VALUATION, execution_provider=ExecutionProvider.MOCK, order_mode=OrderMode.DISABLED)
    )


@dataclass(slots=True)
class ValuationPipeline:
    """
    Read-only P/E valuation operations for CLI menus 5 and 6 (US-101 to US-109).

    It holds no order, signal, account or watchlist dependency, so nothing reachable from here can place an
    order or write the watchlist. The order-gate check walks this object graph to keep it that way: add a
    trading dependency to Pipeline, never here.
    """

    stock_provider: IStockProvider
    fundamentals: FundamentalsFeed
    data_collector: MarketDataCollector
    technical_filter: TechnicalFilter
    news: NewsFeed
    ai_provider: IAiProvider
    prompt_builder: ValuationPromptBuilder
    technical_settings_repository: ITechnicalSettingsRepository
    market_clock: IMarketClock
    scenario_spread: float
    logger: ILoggingProvider

    async def load_market(self) -> MarketValuation:
        """Every listed and OTC stock with its official close, TTM EPS and industry: bulk sources, a few requests."""
        status = valuation_status()
        stocks = [stock.model_copy(deep=True) for stock in await self.stock_provider.get_all()]
        closes = await self.stock_provider.get_latest_closes()

        await self.fundamentals.execute(stocks, status)

        return MarketValuation.of(
            stocks=stocks,
            closes=closes,
            last_closed_session=self.market_clock.last_closed_session(),
            scenario_spread=self.scenario_spread,
            source_warnings=tuple(status.stats.errors),
        )

    async def confirm_technical(self, scan: ValuationScan) -> ValuationScan:
        """US-109 step 2: the active technical strategy, applied exactly as the trading workflows apply it."""
        strategy = (await self.technical_settings_repository.load()).active_strategy
        status = valuation_status()
        stocks = [report.stock for report in scan.survivors]

        await self.data_collector.execute(stocks, status, strategy.indicators)
        await self.technical_filter.execute([stock for stock in stocks if stock.ohlcv], status, strategy)

        return scan.after_technical_step(strategy.strategy_id)

    async def explain(self, report: ValuationReport) -> ValuationExplanation:
        """US-107: the domain computed every number; the AI explains them with the stock's news."""
        stock = report.stock

        if not stock.articles:
            await self.news.execute([stock], valuation_status())

        prompt = self.prompt_builder.build(report)

        try:
            response = await self.ai_provider.generate_reply((Message(role=MessageRole.USER, content=prompt),))
        except Exception as error:
            self.logger.error(f"Valuation explanation failed for {stock.stock_id}: {error}")
            return ValuationExplanation.without_ai(report, f"AI 解釋無法取得：{error}")

        self.ai_provider.save_response(stock.stock_id, response.content)

        return parse_valuation_explanation(report, response.content)
