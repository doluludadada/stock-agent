from a_domain.ports.analysis.technical_settings_repository import ITechnicalSettingsRepository
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.rules.technical.strategy import TechnicalStrategy
from a_domain.types.enums import Workflow
from a_domain.types.errors import TechnicalSettingsConflictError
from b_application.config.app_config import AppConfig


class StrategyLoader:
    """
    Loads the technical strategy one run uses, before the run starts; the run keeps it, so settings saved while it
    runs apply to the next run. Given a built-in strategy id, the CLI session's choice, the run uses that built-in
    strategy and the saved settings stay as they are. Otherwise the owner's saved settings choose: the Buzz strategy
    for Buzz, the active strategy for every other workflow. A save that lands while the settings are read fails that
    read, so the loader reads once more: a run must not fail before its stop-loss SELLs over a settings edit.
    """

    def __init__(
        self, technical_settings_repository: ITechnicalSettingsRepository, config: AppConfig, logger: ILoggingProvider
    ) -> None:
        self._technical_settings_repository = technical_settings_repository
        self._owner_id = config.technical.owner_id
        self._initial_settings = config.technical.initial_settings
        self._built_in_strategies = {strategy.strategy_id: strategy for strategy in config.technical.built_in_strategies}
        self._logger = logger

    async def execute(self, workflow: Workflow, built_in_strategy_id: str | None = None) -> TechnicalStrategy:
        if built_in_strategy_id is not None:
            if (strategy := self._built_in_strategies.get(built_in_strategy_id)) is None:
                raise ValueError(f"No built-in technical strategy {built_in_strategy_id}")

            self._logger.info(f"Technical strategy for {workflow.value}: built-in {strategy.strategy_id}, this session only.")
            return strategy

        try:
            settings = await self._technical_settings_repository.load(self._owner_id, self._initial_settings)
        except TechnicalSettingsConflictError:
            settings = await self._technical_settings_repository.load(self._owner_id, self._initial_settings)

        strategy = settings.buzz_strategy if workflow == Workflow.BUZZ_SCAN else settings.active_strategy
        self._logger.info(f"Technical strategy for {workflow.value}: {strategy.strategy_id}, revision {settings.revision}.")

        return strategy
