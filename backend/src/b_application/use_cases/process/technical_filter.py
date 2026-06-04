# backend/src/b_application/use_cases/process/technical_filter.py

from a_domain.model.market.stock import Stock
from a_domain.ports.analysis.indicator_provider import IIndicatorProvider
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.rules.scoring import TechnicalScoreCalculator
from a_domain.rules.technical.policy import TechnicalScreeningPolicy
from a_domain.types.enums import AnalysisStage
from b_application.schemas.pipeline_context import PipelineContext


class TechnicalFilter:
    """
    Use Case: Apply technical analysis to priced candidates.

    - New candidates must pass technical screening before AI analysis.
    - Held positions must continue even if they fail technical screening because failure may become a SELL or HOLD reason.
    """

    def __init__(
        self,
        indicator_provider: IIndicatorProvider,
        screening_policy: TechnicalScreeningPolicy,
        score_calculator: TechnicalScoreCalculator,
        logger: ILoggingProvider,
    ):
        self._indicator = indicator_provider
        self._policy = screening_policy
        self._calculator = score_calculator
        self._logger = logger

    async def execute(self, context: PipelineContext) -> None:
        stocks = context.priced
        """
        Only stocks with fresh price/history data can be technically evaluated.
        """

        self._logger.info(f"Filtering {len(stocks)} stocks.")

        survivors: list[Stock] = []
        """
        Stocks allowed to continue into NewsFeed and AiAnalyser.
        """

        passed_count = 0
        """
        Counts stocks that truly passed the technical filter.
        Held failed positions may continue, but they should not be counted as technical passes.
        """

        for stock in stocks:
            is_held = stock.stock_id in context.positions_by_stock_id


            if not stock.ohlcv or stock.current_price is None:
                stock.stage = AnalysisStage.FILTERED_FAIL

                if is_held:
                    stock.hard_failures.append("Missing price data for held position")
                    survivors.append(stock)

                continue

            try:
                stock.indicators = self._indicator.calculate_indicators(stock.ohlcv)
                self._policy.evaluate(stock)
                stock.technical_score = self._calculator.calculate(stock)

                if not stock.is_eliminated:
                    stock.stage = AnalysisStage.FILTERED_PASS
                    survivors.append(stock)
                    passed_count += 1
                    continue

                stock.stage = AnalysisStage.FILTERED_FAIL

                if is_held:
                    survivors.append(stock)
                    self._logger.debug(f"Keep held {stock.stock_id} for exit/HOLD decision. Failed: {stock.hard_failures}")
                    continue

                self._logger.debug(f"Drop {stock.stock_id}: Failed {stock.hard_failures}")

            except Exception as e:
                stock.stage = AnalysisStage.FILTERED_FAIL
                error_message = f"Error filtering {stock.stock_id}: {e}"
                self._logger.error(error_message)
                context.stats.add_error(error_message)

                if is_held:
                    stock.hard_failures.append("Technical filter exception for held position")
                    survivors.append(stock)

        context.survivors = survivors
        context.stats.passed_technical += passed_count

        self._logger.info(
            f"Survivors: {len(survivors)}/{len(stocks)} (technical_pass={passed_count}, held_kept={len(survivors) - passed_count})"
        )
