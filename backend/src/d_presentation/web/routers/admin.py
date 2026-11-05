from collections.abc import Awaitable
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Path, Query, status

from a_domain.ports.system.settings_files import SettingsAuditEntry, SettingsDocument, SettingsEdit
from a_domain.types.enums import EditableSetting, LockedSetting, SettingsFile
from a_domain.types.errors import SettingsConflictError, SettingsEditError
from d_presentation.dependencies import AdminToken, RuntimeDependency, running_settings_revision
from d_presentation.web.schemas import (
    EditableSettingResponse,
    SettingsBackupResponse,
    SettingsChangesRequest,
    SettingsEditResponse,
    SettingsFileResponse,
    SettingsFileStatusResponse,
    SettingsRestoreConfirmed,
    SettingsRestoreRequest,
    SettingsSaveRequest,
)

router = APIRouter(prefix="/admin", tags=["Administration"], dependencies=[AdminToken])
"""
The two settings files config/appsetting.yaml and config/instructions.yaml, named only by their SettingsFile id. Only
the allowlisted settings change; the file is validated as the app loads it at startup, saved atomically with a
backup and an audit entry, and applies when the server restarts.
"""

BackupId = Annotated[str, Path(pattern=r"^[0-9]{8}T[0-9]{6}Z-[0-9a-f]{12}$")]
SAVE_ANSWERS: dict[int | str, dict[str, Any]] = {
    status.HTTP_409_CONFLICT: {"description": "The file changed after the revision the request carries; nothing saved."},
    status.HTTP_422_UNPROCESSABLE_CONTENT: {"description": "The app would refuse the file; nothing saved. The detail lists why."},
}


def file_refusal(error: OSError | ValueError) -> HTTPException:
    """
    404 when the file is missing; 403 when it is a symlink, outside config/ or too large, which the editor never follows
    or reads. 409 says only that another save came first. A missing file's error holds its full path, so the answer
    says it in words instead.
    """
    if isinstance(error, FileNotFoundError):
        return HTTPException(status.HTTP_404_NOT_FOUND, "The settings file is missing from config/.")

    return HTTPException(status.HTTP_403_FORBIDDEN, str(error))


async def read_document(runtime: RuntimeDependency, file: SettingsFile) -> SettingsDocument:
    try:
        return await runtime.settings_files.read(file)
    except (PermissionError, ValueError, FileNotFoundError) as error:
        raise file_refusal(error) from error


async def file_status(runtime: RuntimeDependency, file: SettingsFile) -> SettingsFileStatusResponse:
    document = await read_document(runtime, file)
    running = running_settings_revision(runtime, file)
    return SettingsFileStatusResponse(
        file=file,
        revision=document.revision,
        running_revision=running,
        modified_at=document.modified_at,
        restart_required=document.revision != running,
    )


def edit_response(runtime: RuntimeDependency, edit: SettingsEdit) -> SettingsEditResponse:
    revision = edit.saved.revision if edit.saved else edit.revision
    return SettingsEditResponse(
        file=edit.file,
        base_revision=edit.base_revision,
        revision=revision,
        changed=list(edit.changed),
        diff=list(edit.diff),
        problems=list(edit.problems),
        values=edit.values,
        saved=edit.saved is not None,
        restart_required=revision != running_settings_revision(runtime, edit.file),
    )


async def saved_or_refused(runtime: RuntimeDependency, edit_call: Awaitable[SettingsEdit]) -> SettingsEditResponse:
    try:
        edit = await edit_call
    except SettingsConflictError as error:
        raise HTTPException(status.HTTP_409_CONFLICT, str(error)) from error
    except SettingsEditError as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error)) from error
    except (PermissionError, ValueError, FileNotFoundError) as error:
        raise file_refusal(error) from error

    if edit.saved is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, {"problems": list(edit.problems), "diff": list(edit.diff)})

    return edit_response(runtime, edit)


@router.get("/settings/{file}")
async def get_settings_file(file: SettingsFile, runtime: RuntimeDependency) -> SettingsFileResponse:
    """The file's allowlisted settings with their values in the file, and the read-only settings it shows."""
    document = await read_document(runtime, file)
    editable = [setting for setting in EditableSetting if setting.file == file]
    values = runtime.settings_files.values(document.text, [setting.value for setting in editable])
    locked = (
        runtime.settings_files.values(document.text, [setting.value for setting in LockedSetting])
        if file == SettingsFile.APPSETTING
        else {}
    )

    return SettingsFileResponse(
        status=await file_status(runtime, file),
        settings=[
            EditableSettingResponse(setting=setting, value=values.get(setting.value), choices=list(setting.choices))
            for setting in editable
        ],
        locked={LockedSetting(path): value for path, value in locked.items()},
    )


@router.post("/settings/{file}/preview")
async def preview_settings_change(
    file: SettingsFile, body: SettingsChangesRequest, runtime: RuntimeDependency
) -> SettingsEditResponse:
    """The change on the current file: its diff and why the app would refuse it. Nothing is written."""
    try:
        edit = await runtime.pipeline.preview_settings_file(file, changes=body.changes)
    except SettingsEditError as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error)) from error

    return edit_response(runtime, edit)


@router.put("/settings/{file}", responses=SAVE_ANSWERS)
async def save_settings_change(file: SettingsFile, body: SettingsSaveRequest, runtime: RuntimeDependency) -> SettingsEditResponse:
    """Saves the change when the app would start with it and the file is still at `revision`. It applies at the next start."""
    return await saved_or_refused(runtime, runtime.pipeline.save_settings_file(file, body.revision, changes=body.changes))


@router.get("/settings/{file}/backups")
async def list_settings_backups(file: SettingsFile, runtime: RuntimeDependency) -> list[SettingsBackupResponse]:
    return [SettingsBackupResponse.model_validate(backup) for backup in await runtime.settings_files.backups(file)]


@router.post("/settings/{file}/backups/{backup_id}/preview")
async def preview_settings_restore(
    file: SettingsFile, backup_id: BackupId, body: SettingsRestoreRequest, runtime: RuntimeDependency
) -> SettingsEditResponse:
    """The backup against the current file: its diff and problems. Nothing is written."""
    try:
        edit = await runtime.pipeline.preview_settings_file(file, backup_id=backup_id)
    except SettingsEditError as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(error)) from error

    return edit_response(runtime, edit)


@router.post("/settings/{file}/backups/{backup_id}/restore", responses=SAVE_ANSWERS)
async def restore_settings_backup(
    file: SettingsFile, backup_id: BackupId, body: SettingsRestoreConfirmed, runtime: RuntimeDependency
) -> SettingsEditResponse:
    """Puts the backup back through the same validation, revision check, backup and audit as a save."""
    return await saved_or_refused(runtime, runtime.pipeline.save_settings_file(file, body.revision, backup_id=backup_id))


@router.get("/audit")
async def get_settings_audit(runtime: RuntimeDependency, limit: Annotated[int, Query(ge=1, le=200)] = 50) -> list[SettingsAuditEntry]:
    """The latest saves and restores, newest first: when, which file, which revisions and which settings. No value."""
    return await runtime.settings_files.audit_entries(limit)
