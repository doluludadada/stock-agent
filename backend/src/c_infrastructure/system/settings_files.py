import asyncio
import difflib
import io
import json
import os
import re
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, override
from uuid import uuid4

import yaml
from pydantic import TypeAdapter
from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap
from ruamel.yaml.scalarstring import LiteralScalarString

from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.ports.system.settings_files import ISettingsFiles, SettingsAuditEntry, SettingsBackup, SettingsDocument
from a_domain.types.enums import SettingsFile
from a_domain.types.errors import SettingsConflictError, SettingsEditError
from b_application.config.settings_loader import (
    InvalidSettingsError,
    TradingSetupError,
    load_settings,
    settings_revision,
    validate_trading_environment,
)


class SettingsFiles(ISettingsFiles):
    """
    config/appsetting.yaml and config/instructions.yaml, edited in place. A save checks the revision under a lock,
    copies the old text to <project>/.settings-admin/backups/<file>/, writes the new text to a temporary file next to
    the original with the original's permissions, flushes it to disk and renames it over the original, so a crash
    leaves the old or the new file whole. Each save appends one line to .settings-admin/audit.jsonl. The admin folder
    is outside config/ and the frontend, created owner-only (0700), and keeps the latest `backups_kept` backups.

    A file that is a symlink, or that resolves outside config/, is refused. Values go in through ruamel's round-trip
    mode, which keeps comments and every setting it does not touch; nothing in a file is ever executed.
    """

    def __init__(self, project_root: Path, max_bytes: int, backups_kept: int, logger: ILoggingProvider) -> None:
        self._config_folder = (project_root / "config").resolve()
        self._admin_folder = project_root / ".settings-admin"
        self._max_bytes = max_bytes
        self._backups_kept = backups_kept
        self._logger = logger
        self._lock = asyncio.Lock()
        self._audit = TypeAdapter(SettingsAuditEntry)
        self._yaml = YAML(typ="rt")
        self._yaml.preserve_quotes = True
        self._yaml.width = 4096

    @override
    async def read(self, file: SettingsFile) -> SettingsDocument:
        path = self._config_folder / file.file_name

        if path.is_symlink() or path.resolve().parent != self._config_folder:
            raise PermissionError(f"{file.file_name} is not a regular file inside config/")

        if path.stat().st_size > self._max_bytes:
            raise ValueError(f"{file.file_name} is larger than {self._max_bytes} bytes")

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

            await self.keep_backup(current)
            saved = await self.write(file, text)
            await self.record(entry)

        self._logger.info(f"Settings file {file.file_name} saved: {current.revision[:12]} -> {saved.revision[:12]}")

        return saved

    @override
    async def keep_backup(self, document: SettingsDocument) -> SettingsBackup:
        folder = self._admin_folder / "backups" / document.file.value

        for level in (self._admin_folder, folder.parent, folder):
            level.mkdir(mode=0o700, exist_ok=True)

        created_at = datetime.now(UTC)
        backup_id = f"{created_at:%Y%m%dT%H%M%SZ}-{uuid4().hex[:12]}"
        path = folder / f"{backup_id}.yaml"
        path.write_text(document.text, encoding="utf-8")
        path.chmod(0o600)

        for stale in sorted(folder.glob("*.yaml"), reverse=True)[self._backups_kept :]:
            stale.unlink()

        return SettingsBackup(backup_id=backup_id, file=document.file, revision=document.revision, created_at=created_at)

    @override
    async def write(self, file: SettingsFile, text: str) -> SettingsDocument:
        path = self._config_folder / file.file_name
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

        return await self.read(file)

    @override
    async def record(self, entry: SettingsAuditEntry) -> None:
        self._admin_folder.mkdir(mode=0o700, exist_ok=True)
        path = self._admin_folder / "audit.jsonl"

        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(self._audit.dump_python(entry, mode="json"), ensure_ascii=False) + "\n")

        path.chmod(0o600)

    @override
    async def backups(self, file: SettingsFile) -> list[SettingsBackup]:
        folder = self._admin_folder / "backups" / file.value

        return [
            SettingsBackup(
                backup_id=path.stem,
                file=file,
                revision=settings_revision(path.read_text(encoding="utf-8")),
                created_at=datetime.strptime(path.stem.split("-")[0], "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC),
            )
            for path in sorted(folder.glob("*.yaml"), reverse=True)
        ]

    @override
    async def backup_text(self, file: SettingsFile, backup_id: str) -> str | None:
        if not re.fullmatch(r"[0-9]{8}T[0-9]{6}Z-[0-9a-f]{12}", backup_id):
            return None

        path = self._admin_folder / "backups" / file.value / f"{backup_id}.yaml"

        return path.read_text(encoding="utf-8") if path.is_file() and not path.is_symlink() else None

    @override
    async def audit_entries(self, limit: int) -> list[SettingsAuditEntry]:
        path = self._admin_folder / "audit.jsonl"

        if not path.exists():
            return []

        lines = path.read_text(encoding="utf-8").splitlines()[-limit:]

        return [self._audit.validate_python(json.loads(line)) for line in reversed(lines)]

    @override
    def revision_of(self, text: str) -> str:
        return settings_revision(text)

    @override
    def values(self, text: str, paths: Sequence[str]) -> dict[str, Any]:
        document = self._yaml.load(text) or CommentedMap()
        found: dict[str, Any] = {}

        for path in paths:
            node: Any = document

            for key in path.split("."):
                node = node.get(key) if isinstance(node, Mapping) else None

            if node is not None:
                found[path] = json.loads(json.dumps(node))

        return found

    @override
    def edited(self, text: str, changes: Mapping[str, Any]) -> str:
        document = self._yaml.load(text) or CommentedMap()

        for path, value in changes.items():
            *sections, key = path.split(".")
            node = document

            for section in sections:
                node = node.setdefault(section, CommentedMap())

            node[key] = LiteralScalarString(value) if isinstance(value, str) and "\n" in value else value

        output = io.StringIO()
        self._yaml.dump(document, output)

        return output.getvalue()

    @override
    def problems(self, file: SettingsFile, text: str) -> list[str]:
        try:
            config = load_settings({file: text})
            validate_trading_environment(config)
        except InvalidSettingsError as error:
            return error.problems
        except (yaml.YAMLError, TradingSetupError, ValueError, TypeError, AttributeError, OSError) as error:
            return [f"{type(error).__name__}: {error}"]

        missing = config.ai.missing_key()
        return [f"ai.active_model: {config.ai.active_model.value} needs {missing} set; the app would not start"] if missing else []

    @override
    def diff(self, file: SettingsFile, before: str, after: str) -> list[str]:
        saved, proposed = f"{file.file_name} (saved)", f"{file.file_name} (proposed)"
        return list(difflib.unified_diff(before.splitlines(), after.splitlines(), saved, proposed, lineterm=""))
