from fastapi import APIRouter

from a_domain.rules.technical.strategy import TechnicalSettings, TechnicalStrategy
from d_presentation.dependencies import RuntimeDependency
from d_presentation.web.schemas import TechnicalSettingsRequest

router = APIRouter()


@router.put("/technical-settings")
async def save_technical_settings(body: TechnicalSettingsRequest, runtime: RuntimeDependency) -> TechnicalSettings:
    return await runtime.pipeline.save_technical_settings(body.settings)


@router.get("/technical-settings/built-in-strategies")
async def get_built_in_strategies(runtime: RuntimeDependency) -> tuple[TechnicalStrategy, ...]:
    return runtime.config.technical.built_in_strategies
