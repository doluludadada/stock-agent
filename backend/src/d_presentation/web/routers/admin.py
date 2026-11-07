from fastapi import APIRouter, Request, status

from a_domain.ports.system.settings_files import SettingField
from d_presentation.web.schemas import ErrorResponse, ProblemsResponse, SettingsSaveRequest
from d_presentation.web.session import (
    CurrentUser,
    EditSystemSettings,
    PrivateAccess,
    RequestHold,
    RuntimeSwitchDependency,
    UserPipeline,
    client_of,
    host_of,
)

router = APIRouter(prefix="/admin", tags=["Administration"], dependencies=[PrivateAccess, EditSystemSettings])
"""
Administrators only (403 otherwise, signed in still). The settings form: every setting of config/appsetting.yaml and
every AI prompt of config/instructions.yaml as a field, from the settings classes; no secret of .env is one. A save
writes its changes into the files in place, is checked as the app starts, needs the administrator's password again,
opens the app on the new files before it writes anything, then writes them atomically with a backup and an audit entry
and runs on them at once.
"""

READ_ANSWERS: dict[int | str, dict] = {
    status.HTTP_422_UNPROCESSABLE_CONTENT: {
        "model": ProblemsResponse,
        "description": "A settings file does not parse (settings_refused); the problem says where.",
    }
}
SAVE_ANSWERS: dict[int | str, dict] = {
    status.HTTP_403_FORBIDDEN: {
        "model": ErrorResponse,
        "description": "A save without the password (password_required), or with a wrong one (password_refused).",
    },
    status.HTTP_409_CONFLICT: {
        "model": ErrorResponse,
        "description": "The server reloaded its settings after the request started, or another save wrote a file first "
        "(settings_conflict); nothing saved.",
    },
    status.HTTP_422_UNPROCESSABLE_CONTENT: {
        "model": ProblemsResponse | ErrorResponse,
        "description": "The app would not start with the new settings (settings_refused, with the problems at their "
        "settings paths), or a change names no field of the form or cannot be written in place (settings_edit_refused).",
    },
    status.HTTP_429_TOO_MANY_REQUESTS: {
        "model": ErrorResponse,
        "description": "Too many wrong passwords from this address (sign_in_throttled); Retry-After says when.",
    },
}


@router.get("/settings", responses=READ_ANSWERS)
async def get_settings(pipeline: UserPipeline) -> list[SettingField]:
    """
    The settings form: each setting by its dotted settings path, in the order of the settings classes, with how the form
    shows it, the value the file on disk sets (else its default, else null), its options and bounds, and whether it
    applies only at a restart. The AI prompts of instructions.yaml are fields at their settings paths, such as
    ai.system_prompt.
    """
    return await pipeline.load_settings_form()


@router.put("/settings", responses=SAVE_ANSWERS)
async def save_settings(
    body: SettingsSaveRequest,
    request: Request,
    opened: RequestHold,
    user: CurrentUser,
    switch: RuntimeSwitchDependency,
    pipeline: UserPipeline,
) -> list[SettingField]:
    """
    Writes every change into its settings file in place, every other line, comment and key as it was, opens the app on
    the new files, writes them and runs on them at once, when the app starts with them and the password is the
    administrator's own; or refuses with nothing written and the app as it was. A change to the value its field shows
    is skipped, and changes that change nothing write nothing. Runs that started earlier finish on the settings they
    started with. The answer is the form after the save.
    """
    await switch.save(opened, user, body.changes, password=body.password, client=client_of(request), host=host_of(request))
    return await pipeline.load_settings_form()
