from a_domain.model.market.stock import Stock
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.rules.scoring.technical import TechnicalScoreCalculator
from b_application.factories import TechnicalPolicyFactory
from b_application.schemas.config import AppConfig
from b_application.schemas.pipeline_status import PipelineStatus


class TechnicalFilter:
    """
    Applies technical rules to analysis candidates.
    """

    def __init__(
        self,
        config: AppConfig,
        logger: ILoggingProvider,
    ) -> None:
        self._logger = logger
        self._policy = TechnicalPolicyFactory().create(
            config.analysis.active_strategy,
            config.strategy,
        )
        self._score_calculator = TechnicalScoreCalculator(
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

    async def execute(
        self,
        stocks: list[Stock],
        status: PipelineStatus,
        include_entry_timing: bool = True,
    ) -> list[Stock]:
        self._logger.info(f"Filtering {len(stocks)} stocks.")

        survivors: list[Stock] = []

        for stock in stocks:
            self._policy.evaluate(stock, include_entry_timing=include_entry_timing)
            stock.technical_score = self._score_calculator.calculate(stock)

            if not stock.is_eliminated:
                survivors.append(stock)

        status.stats.passed_technical += len(survivors)

        self._logger.info(f"{len(survivors)} stocks passed technical filter.")

        return survivors