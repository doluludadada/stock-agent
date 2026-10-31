# backend/src/b_application/use_cases/process/technical_filter.py

from a_domain.model.market.stock import Stock
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.rules.technical.calculation import TechnicalIndicatorCalculator
from a_domain.rules.technical.strategy import TechnicalStrategy
from b_application.schemas.pipeline_status import PipelineStatus


class TechnicalFilter:
    """
    Evaluates stocks using a workflow-selected technical strategy: it calculates the strategy's indicators from each
    stock's daily history, then applies the strategy's rules.

    The use case applies a strategy but does not decide which strategy
    belongs to Full Cycle, Buzz, Manual, or another workflow.
    """

    def __init__(self, logger: ILoggingProvider) -> None:
        self._logger = logger

    async def execute(self, stocks: list[Stock], status: PipelineStatus, strategy: TechnicalStrategy) -> list[Stock]:
        self._logger.info(f"Filtering {len(stocks)} stocks with the selected technical strategy.")
        calculator = TechnicalIndicatorCalculator(strategy.indicators)
        survivors: list[Stock] = []

        for stock in stocks:
            try:
                stock.indicators = calculator.apply(stock.ohlcv)
            except Exception as error:
                message = f"Failed to process market data for {stock.stock_id}: {error}"
                self._logger.error(message)
                status.stats.add_error(message)

            stock.technical_report = strategy.apply(stock)

            if stock.technical_report.passed:
                survivors.append(stock)

        rejected_count = len(stocks) - len(survivors)
        status.stats.passed_technical += len(survivors)

        self._logger.info(f"Technical filtering completed. Passed={len(survivors)}, Rejected={rejected_count}.")

        return survivors
