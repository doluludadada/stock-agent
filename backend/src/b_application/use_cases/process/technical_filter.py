from a_domain.model.market.stock import Stock
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.rules.scoring import TechnicalScoreCalculator
from a_domain.rules.technical.policy.technical_screening_policy import TechnicalScreeningPolicy
from b_application.schemas.pipeline_status import PipelineStatus


class TechnicalFilter:
    """
    Applies structural technical screening and assigns technical_score.

    This use case does not decide entry timing.
    Entry timing belongs to the BUY decision path.
    """

    def __init__(
        self,
        policy: TechnicalScreeningPolicy,
        score_calculator: TechnicalScoreCalculator,
        logger: ILoggingProvider,
    ) -> None:
        self._policy = policy
        self._score_calculator = score_calculator
        self._logger = logger

    async def execute(
        self,
        stocks: list[Stock],
        status: PipelineStatus,
    ) -> list[Stock]:
        self._logger.info(f"Filtering {len(stocks)} stocks.")

        survivors: list[Stock] = []

        for stock in stocks:
            self._policy.evaluate(stock)
            stock.technical_score = self._score_calculator.calculate(stock)

            if not stock.is_eliminated:
                survivors.append(stock)

        status.stats.passed_technical += len(survivors)

        self._logger.info(f"{len(survivors)} stocks passed technical filter.")

        return survivors
