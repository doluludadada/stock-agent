from typing import Any

from fastapi import APIRouter, status

from a_domain.rules.technical.strategy import TechnicalSettings, TechnicalStrategy
from d_presentation.dependencies import ApiToken, RuntimeDependency
from d_presentation.web.schemas import TechnicalSettingsRequest

router = APIRouter(prefix="/technical-settings", tags=["Technical settings"])

CONFLICT: dict[int | str, dict[str, Any]] = {status.HTTP_409_CONFLICT: {"description": "Another save came first"}}


@router.get("", dependencies=[ApiToken], responses=CONFLICT)
async def get_technical_settings(runtime: RuntimeDependency) -> TechnicalSettings:
    """
    The owner's strategies and which one each workflow uses, with the revision a save must carry. The first read
    copies every built-in strategy for the owner. A workflow already running keeps the strategy it started with. A
    save that lands during the read answers 409: read again.
    """
    return await runtime.pipeline.load_technical_settings()


@router.put("", dependencies=[ApiToken], responses=CONFLICT)
async def save_technical_settings(body: TechnicalSettingsRequest, runtime: RuntimeDependency) -> TechnicalSettings:
    """
    Replaces the owner's settings as a whole, for the next workflow. Invalid settings save nothing and answer 422 with
    one error per field under body.settings. Settings read before another save answer 409 and save nothing: read
    them again, reapply the change, and save with the new revision.
    """
    return await runtime.pipeline.save_technical_settings(body.settings)


@router.get("/built-in-strategies")
async def get_built_in_strategies(runtime: RuntimeDependency) -> tuple[TechnicalStrategy, ...]:
    """The developer's strategies. A client copies one under its own strategy_id to start an owner's strategy from it."""
    return runtime.config.technical.built_in_strategies
