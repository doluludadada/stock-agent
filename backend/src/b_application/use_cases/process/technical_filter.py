# backend/src/b_application/use_cases/process/technical_filter.py

from icontract import require

from a_domain.model.market.stock import Stock
from a_domain.ports.analysis.indicator_provider import IIndicatorProvider
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.rules.scoring import TechnicalScoreCalculator
from a_domain.types.enums import AnalysisStage
from b_application.factories import TechnicalPolicyFactory
from b_application.schemas.config import AppConfig
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
        config: AppConfig,
        logger: ILoggingProvider,
    ):
        self._indicator = indicator_provider
        self._policy = TechnicalPolicyFactory().create(config.analysis.active_strategy, config.strategy)
        self._calculator = TechnicalScoreCalculator(
            base=config.scoring.base,
            pass_bonus=config.scoring.pass_bonus,
            hard_failure_penalty=config.scoring.hard_failure_penalty,
            max_hard_penalty=config.scoring.max_hard_penalty,
            soft_failure_penalty=config.scoring.soft_failure_penalty,
            max_soft_penalty=config.scoring.max_soft_penalty,
            rsi_sweet_spot_bonus=config.scoring.rsi_sweet_spot_bonus,
            rsi_sweet_spot_min=config.scoring.rsi_sweet_spot_min,
            rsi_sweet_spot_max=config.scoring.rsi_sweet_spot_max,
            macd_bullish_bonus=config.scoring.macd_bullish_bonus,
            ma_present_bonus=config.scoring.ma_present_bonus,
        )
        self._logger = logger

    @require(lambda context: len(context.candidates) > 0, "Pipeline stocks should be exist")
    async def execute(self, context: PipelineContext) -> None:
        stocks = context.candidates
        """
        Only stocks with fresh price/history data can be technically evaluated.
        """

        self._logger.info(f"Filtering {len(stocks)} stocks.")

        passed_count = 0
        """
        Counts stocks that truly passed the technical filter.
        Held failed positions may continue, but they should not be counted as technical passes.
        """

        # TODO:  After scanning add to survivors
