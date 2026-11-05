from a_domain.rules.technical.strategy import TechnicalSettings
from a_domain.rules.technical.strategy import TechnicalStrategy
from fastapi import APIRouter
from pydantic import TypeAdapter

from d_presentation.dependencies import RuntimeDependency

router = APIRouter()


@router.put("/technical-settings")
async def save_technical_settings(body: dict[str, object], runtime: RuntimeDependency) -> TechnicalSettings:
    settings = TypeAdapter(TechnicalSettings).validate_python(body)
    return await runtime.pipeline.save_technical_settings(settings)


@router.get("/technical-settings/strategy-fields")
async def get_strategy_fields() -> list[str]:
    return list(TechnicalStrategy.__dataclass_fields__)
