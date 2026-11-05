from typing import Annotated

from fastapi import APIRouter, Path, Query, Request, status

from a_domain.ports.system.settings_files import BackupId, SettingsDocument, SettingsEdit
from a_domain.types.enums import SettingsFile
from d_presentation.web.schemas import (
    Confirmed,
    ErrorResponse,
    ProblemsResponse,
    SettingsAuditEntryResponse,
    SettingsBackupResponse,
    SettingsDocumentResponse,
    SettingsEditResponse,
    SettingsFileStatusResponse,
    SettingsOverviewResponse,
    SettingsRestoreConfirmed,
    SettingsRestoreRequest,
    SettingsSaveRequest,
    SettingsTextRequest,
)
from d_presentation.web.session import (
    CurrentUser,
    EditSystemSettings,
    PrivateAccess,
    RequestHold,
    RuntimeDependency,
    RuntimeSwitchDependency,
    UserPipeline,
    client_of,
    host_of,
)

router = APIRouter(prefix="/admin", tags=["Administration"], dependencies=[PrivateAccess, EditSystemSettings])
"""
Administrators only (403 otherwise, signed in still). Every YAML settings file of config/, named only by its
SettingsFile id and edited as a whole text. A save or a restore is checked as the app starts, needs the administrator's
password again, opens the app on the new text before it writes anything, then writes it atomically with a backup and
an audit entry and runs on it at once.
"""

BackupPath = Annotated[BackupId, Path()]
SAVE_ANSWERS: dict[int | str, dict] = {
    status.HTTP_403_FORBIDDEN: {
        "model": ErrorResponse,
        "description": "A save or a restore without the password (password_required), or with a wrong one (password_refused).",
    },
    status.HTTP_409_CONFLICT: {
        "model": ErrorResponse,
        "description": "The file changed after the revision the request carries; nothing saved.",
    },
    status.HTTP_422_UNPROCESSABLE_CONTENT: {"model": ProblemsResponse, "description": "The app would not start with it."},
    status.HTTP_429_TOO_MANY_REQUESTS: {
        "model": ErrorResponse,
        "description": "Too many wrong passwords from this address; Retry-After says when.",
    },
}


def file_status(document: SettingsDocument, switch: RuntimeSwitchDependency) -> SettingsFileStatusResponse:
    return SettingsFileStatusResponse(
        file=document.file,
        file_name=document.file.file_name,
        revision=document.revision,
        running_revision=switch.status.running.get(document.file),
        modified_at=document.modified_at,
    )


def edit_response(edit: SettingsEdit, switch: RuntimeSwitchDependency) -> SettingsEditResponse:
    revision = edit.saved.revision if edit.saved else edit.revision
    running = switch.status.running.get(edit.file)
    return SettingsEditResponse(
        file=edit.file,
        base_revision=edit.base_revision,
        revision=revision,
        running_revision=running,
        changed=list(edit.changed),
        diff=list(edit.diff),
        problems=list(edit.problems),
        saved=edit.saved is not None,
        applied=revision == running,
    )


@router.get("/settings")
async def get_settings_overview(
    pipeline: UserPipeline, runtime: RuntimeDependency, switch: RuntimeSwitchDependency
) -> SettingsOverviewResponse:
    """
    Every settings file with its revision on disk and the one the server runs on, an edit on disk the server refused and
    why, how many earlier settings still finish runs, and what applies only at a restart.
    """
    return await overview(pipeline, runtime, switch)


@router.post("/settings/reload")
async def reload_settings(
    body: Confirmed, pipeline: UserPipeline, runtime: RuntimeDependency, switch: RuntimeSwitchDependency
) -> SettingsOverviewResponse:
    """
    The administrator's try again: loads the settings files as they are on disk now, an edit the server refused
    before included, since a refusal can come from outside the files (a database that was down, a broker login that
    failed). The server runs on them when they start, and the answer's `refused` is null; or it keeps its settings,
    and `refused` says why.
    """
    await switch.retry()
    return await overview(pipeline, runtime, switch)


async def overview(pipeline: UserPipeline, runtime: RuntimeDependency, switch: RuntimeSwitchDependency) -> SettingsOverviewResponse:
    documents = [await pipeline.read_settings_file(file) for file in SettingsFile]
    status = switch.status
    return SettingsOverviewResponse(
        environment=runtime.config.environment,
        files=[file_status(document, switch) for document in documents],
        refused=status.refused,
        draining=status.draining,
    )


@router.get("/settings/{file}")
async def get_settings_file(file: SettingsFile, pipeline: UserPipeline, switch: RuntimeSwitchDependency) -> SettingsDocumentResponse:
    """The whole file as it is on disk, with its revision and the one the server runs on."""
    document = await pipeline.read_settings_file(file)
    return SettingsDocumentResponse(status=file_status(document, switch), text=document.text)


@router.post("/settings/{file}/preview")
async def preview_settings_file(
    file: SettingsFile, body: SettingsTextRequest, request: Request, pipeline: UserPipeline, switch: RuntimeSwitchDependency
) -> SettingsEditResponse:
    """
    The text against the file on disk: its diff, the settings it changes, those applying only at a restart, and its
    problems at their line and column. Nothing is written.
    """
    return edit_response(await pipeline.preview_settings_file(file, body.revision, host_of(request), text=body.text), switch)


@router.put("/settings/{file}", responses=SAVE_ANSWERS)
async def save_settings_file(
    file: SettingsFile,
    body: SettingsSaveRequest,
    request: Request,
    opened: RequestHold,
    user: CurrentUser,
    switch: RuntimeSwitchDependency,
) -> SettingsEditResponse:
    """
    Opens the app on the whole new text, writes it and runs on it at once, when the app starts with it, the file is
    still at `revision` and the password is the administrator's own; or refuses with nothing written and the app as it
    was. Runs that started earlier finish on the settings they started with.
    """
    client, host = client_of(request), host_of(request)
    edit = await switch.save(opened, user, file, body.revision, text=body.text, password=body.password, client=client, host=host)
    return edit_response(edit, switch)


@router.get("/settings/{file}/backups")
async def list_settings_backups(file: SettingsFile, pipeline: UserPipeline) -> list[SettingsBackupResponse]:
    return [SettingsBackupResponse.model_validate(backup) for backup in await pipeline.list_settings_backups(file)]


@router.post("/settings/{file}/backups/{backup_id}/preview")
async def preview_settings_restore(
    file: SettingsFile,
    backup_id: BackupPath,
    body: SettingsRestoreRequest,
    request: Request,
    pipeline: UserPipeline,
    switch: RuntimeSwitchDependency,
) -> SettingsEditResponse:
    """The backup's whole text against the file on disk, reviewed as a save would be. Nothing is written."""
    return edit_response(await pipeline.preview_settings_file(file, body.revision, host_of(request), backup_id=backup_id), switch)


@router.post("/settings/{file}/backups/{backup_id}/restore", responses=SAVE_ANSWERS)
async def restore_settings_backup(
    file: SettingsFile,
    backup_id: BackupPath,
    body: SettingsRestoreConfirmed,
    request: Request,
    opened: RequestHold,
    user: CurrentUser,
    switch: RuntimeSwitchDependency,
) -> SettingsEditResponse:
    """Puts the backup's whole text back through the same checks, password, startup, backup, audit and swap as a save."""
    client, host = client_of(request), host_of(request)
    edit = await switch.save(opened, user, file, body.revision, backup_id=backup_id, password=body.password, client=client, host=host)
    return edit_response(edit, switch)


@router.get("/audit")
async def get_settings_audit(
    pipeline: UserPipeline, limit: Annotated[int, Query(ge=1, le=200)] = 50
) -> list[SettingsAuditEntryResponse]:
    """The latest saves and restores, newest first: when, which file, by whom, which revisions and which settings. No value."""
    return [
        SettingsAuditEntryResponse(
            recorded_at=entry.recorded_at,
            file=entry.file,
            action=entry.action,
            actor=entry.actor,
            actor_name=actor.username if actor else None,
            from_revision=entry.from_revision,
            to_revision=entry.to_revision,
            settings=list(entry.settings),
        )
        for entry, actor in await pipeline.load_settings_audit(limit)
    ]
