from a_domain.model.market.stock import Stock
from a_domain.ports.system.logging_provider import ILoggingProvider
from b_application.factories import TechnicalPolicyFactory
from b_application.schemas.config import AppConfig
from b_application.schemas.pipeline_context import PipelineContext


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

    async def execute(
        self,
        stocks: list[Stock],
        context: PipelineContext,
    ) -> list[Stock]:
        self._logger.info(f"Filtering {len(stocks)} stocks.")

        survivors: list[Stock] = []

        for stock in stocks:
            self._policy.evaluate(stock)

            if not stock.is_eliminated:
                survivors.append(stock)

        context.stats.passed_technical += len(survivors)

        self._logger.info(f"{len(survivors)} stocks passed technical filter.")

        return survivors
