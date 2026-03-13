from a_domain.model.market.stock import Stock
from a_domain.ports.analysis.indicator_provider import IIndicatorProvider
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.rules.process.policies.technical_screening import TechnicalScreeningPolicy
from a_domain.rules.process.scoring.technical import TechnicalScoreCalculator
from a_domain.types.enums import AnalysisStage
from b_application.schemas.pipeline_context import PipelineContext


class TechnicalFilter:
    """
    Use Case: Filter stocks through technical analysis.
    The funnel gatekeeper — only survivors pass to the next stage."""

    def __init__(
        self,
        tech_provider: IIndicatorProvider,
        screening_policy: TechnicalScreeningPolicy,
        score_calculator: TechnicalScoreCalculator,
        logger: ILoggingProvider,
    ):
        self._tech_provider = tech_provider
        self._policy = screening_policy
        self._calculator = score_calculator
        self._logger = logger

    def execute(self, ctx: PipelineContext) -> None:
        stocks = ctx.priced
        self._logger.info(f"Filtering {len(stocks)} stocks...")
        survivors: list[Stock] = []

        for stock in stocks:
            if not stock.ohlcv or stock.current_price is None:
                stock.stage = AnalysisStage.FILTERED_FAIL
                continue

            try:
                stock.indicators = self._tech_provider.calculate_indicators(stock.ohlcv)

                self._policy.evaluate(stock)

                stock.technical_score = self._calculator.calculate(stock)

                if not stock.is_eliminated:
                    stock.stage = AnalysisStage.FILTERED_PASS
                    survivors.append(stock)
                else:
                    stock.stage = AnalysisStage.FILTERED_FAIL
                    self._logger.debug(f"Drop {stock.stock_id}: Failed {stock.hard_failures}")
            except Exception as e:
                self._logger.error(f"Error filtering {stock.stock_id}: {e}")
                stock.stage = AnalysisStage.FILTERED_FAIL

        ctx.survivors = survivors
        ctx.stats.passed_technical += len(survivors)
        self._logger.info(f"Survivors: {len(survivors)}/{len(stocks)}")
