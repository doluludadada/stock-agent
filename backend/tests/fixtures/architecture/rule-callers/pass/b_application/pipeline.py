from a_domain.rules.technical.strategy import TechnicalSettings, TechnicalStrategy
from b_application.use_cases.process.strategy_loader import StrategyLoader
from b_application.use_cases.process.technical_settings_editor import TechnicalSettingsEditor


class Pipeline:
    strategy_loader: StrategyLoader
    technical_settings_editor: TechnicalSettingsEditor

    async def save_technical_settings(self, settings: TechnicalSettings) -> TechnicalSettings:
        return await self.technical_settings_editor.execute(settings)

    async def load_strategies(self) -> tuple[TechnicalStrategy, ...]:
        return await self.strategy_loader.execute()
