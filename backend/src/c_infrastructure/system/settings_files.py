import asyncio
import json
import os
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import override
from uuid import uuid4

from pydantic import TypeAdapter

from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.system.settings_files import ISettingsFiles, SettingsAuditEntry, SettingsBackup, SettingsDocument, SettingsProblem
from a_domain.types.enums import Audience, SettingsFile, SystemEnvironment
from a_domain.types.errors import SettingsConflictError, SettingsEditError, SettingsFileMissing, SettingsFileRefused
from b_application.config.settings_loader import (
    InvalidSettingsError,
    settings_revision,
    settings_texts,
    startup_settings,
    validate_editor_reachable,
)


class SettingsFiles(ISettingsFiles):
    """
    config/appsetting.yaml and config/instructions.yaml, written in place. A save checks the revision under a lock,
    copies the old text to <project>/.settings-admin/backups/<file>/, writes the new text to a temporary file next to
    the original with the original's permissions, flushes it to disk and renames it over the original, so a crash
    leaves the old or the new file whole. Each save appends one line to .settings-admin/audit.jsonl before it writes,
    so an audit that cannot be written stops the save with the file and the running app as they were. The admin folder
    is outside config/ and the frontend, created owner-only (0700), and keeps the latest `backups_kept` backups.

    A file that is a symlink, or that resolves outside config/, is refused. The new text is written byte for byte;
    nothing in a file is ever executed (YAML is read with the safe loader only).
    """

    def __init__(self, project_root: Path, max_bytes: int, backups_kept: int, logger: ILoggingProvider) -> None:
        self._project_root = project_root
        self._config_folder = (project_root / "config").resolve()
        self._admin_folder = project_root / ".settings-admin"
        self._max_bytes = max_bytes
        self._backups_kept = backups_kept
        self._logger = logger
        self._lock = asyncio.Lock()
        self._audit = TypeAdapter(SettingsAuditEntry)

    @override
    async def read(self, file: SettingsFile) -> SettingsDocument:
        path = self._config_folder / file.file_name

        if not path.exists():
            raise SettingsFileMissing(f"{file.file_name} is missing from config/.")

        if path.is_symlink() or path.resolve().parent != self._config_folder:
            raise SettingsFileRefused(f"{file.file_name} is not a regular file inside config/")

        if path.stat().st_size > self._max_bytes:
            raise SettingsFileRefused(f"{file.file_name} is larger than {self._max_bytes} bytes")

        text = path.read_text(encoding="utf-8")
        modified_at = datetime.fromtimestamp(path.stat().st_mtime, UTC)

        return SettingsDocument(file=file, text=text, revision=settings_revision(text), modified_at=modified_at)

    @override
    async def replace(self, file: SettingsFile, text: str, expected_revision: str, entry: SettingsAuditEntry) -> SettingsDocument:
        if len(text.encode("utf-8")) > self._max_bytes:
            raise SettingsEditError(f"The new {file.file_name} would be larger than {self._max_bytes} bytes")

        async with self._lock:
            current = await self.read(file)

            if current.revision != expected_revision:
                raise SettingsConflictError(f"{file.file_name} changed since revision {expected_revision[:12]}; read it again")

            await keep_backup(current, self._admin_folder, self._backups_kept)
            await record_audit(entry, self._admin_folder, self._audit)
            await write_settings_file(file, text, self._config_folder)
            saved = await self.read(file)

        self._logger.info(f"Settings file {file.file_name} saved: {current.revision[:12]} -> {saved.revision[:12]}")

        return saved

    @override
    def built_in_strategy_ids(self) -> list[str]:
        return sorted(path.stem for path in (self._project_root / "config" / "strategies").glob("*.json"))

    @override
    def check(
        self, candidates: Mapping[SettingsFile, str], environment: SystemEnvironment, audience: Audience, host: str
    ) -> tuple[SettingsProblem, ...]:
        texts = settings_texts(self._project_root, candidates)

        try:
            validate_editor_reachable(startup_settings(self._project_root, texts, environment, audience), texts, host)
        except InvalidSettingsError as error:
            return tuple(error.problems)

        return ()


async def keep_backup(document: SettingsDocument, admin_folder: Path, backups_kept: int) -> SettingsBackup:
    """Copies the text a save is about to replace, owner-only, and drops the backups beyond the kept count."""
    folder = admin_folder / "backups" / document.file.value

    for level in (admin_folder, folder.parent, folder):
        level.mkdir(mode=0o700, exist_ok=True)

    created_at = datetime.now(UTC)
    backup_id = f"{created_at:%Y%m%dT%H%M%SZ}-{uuid4().hex[:12]}"
    path = folder / f"{backup_id}.yaml"
    path.write_text(document.text, encoding="utf-8")
    path.chmod(0o600)

    for stale in sorted(folder.glob("*.yaml"), reverse=True)[backups_kept:]:
        stale.unlink()

    return SettingsBackup(backup_id=backup_id, file=document.file, revision=document.revision, created_at=created_at)


async def write_settings_file(file: SettingsFile, text: str, config_folder: Path) -> None:
    """Replaces the file atomically: a temporary file in the same folder, flushed to disk, renamed over it."""
    path = config_folder / file.file_name
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    mode = path.stat().st_mode & 0o777

    try:
        with temporary.open("w", encoding="utf-8", newline="") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.chmod(mode)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


async def record_audit(entry: SettingsAuditEntry, admin_folder: Path, audit: TypeAdapter[SettingsAuditEntry]) -> None:
    """Appends the audit entry, owner-only. It holds setting paths and revisions, never a value."""
    admin_folder.mkdir(mode=0o700, exist_ok=True)
    path = admin_folder / "audit.jsonl"

    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(audit.dump_python(entry, mode="json"), ensure_ascii=False) + "\n")

    path.chmod(0o600)
