from typing import Any

from fastapi import APIRouter
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError

from c_infrastructure.technical.technical_settings_schema import TechnicalSettingsSchema
from d_presentation.web.dependencies import RuntimeDependency, WritePermission
from d_presentation.web.schemas import Confirmed, TechnicalSettingsRequest

router = APIRouter(prefix="/technical-settings", tags=["Technical settings"])


async def current_document(runtime: RuntimeDependency) -> dict[str, Any]:
    return TechnicalSettingsSchema.from_domain(await runtime.technical_settings_repository.load()).to_document()


@router.get("")
async def get_technical_settings(runtime: RuntimeDependency) -> dict[str, Any]:
    """
    The settings the next workflow will use: the active and Buzz strategy ids, and each strategy's indicator parameters,
    scoring and rules. A workflow already running keeps the settings it started with.
    """
    return await current_document(runtime)


@router.get("/schema")
async def get_technical_settings_schema() -> dict[str, Any]:
    """The JSON schema of the settings document, with each field's type and bounds."""
    return TechnicalSettingsSchema.model_json_schema()


@router.put("", dependencies=[WritePermission])
async def save_technical_settings(body: TechnicalSettingsRequest, runtime: RuntimeDependency) -> dict[str, Any]:
    """
    Validates the whole document and saves it to config/technical.local.yaml for the next workflow. An invalid document
    saves nothing and answers 422 with one error per field, located under body.settings.
    """
    try:
        settings = TechnicalSettingsSchema.model_validate(body.settings).to_domain()

    except ValidationError as error:
        raise RequestValidationError(
            [
                {"loc": ("body", "settings", *detail["loc"]), "msg": detail["msg"], "type": detail["type"]}
                for detail in error.errors(include_url=False, include_context=False, include_input=False)
            ]
        ) from error

    await runtime.technical_settings_repository.save(settings)

    return await current_document(runtime)


@router.post("/reset", dependencies=[WritePermission])
async def reset_technical_settings(body: Confirmed, runtime: RuntimeDependency) -> dict[str, Any]:
    """Deletes config/technical.local.yaml, so the next workflow uses config/technical.yaml again."""
    await runtime.technical_settings_repository.reset()

    return await current_document(runtime)
