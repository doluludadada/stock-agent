from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Annotated, Any, Protocol

from pydantic import Field
from pydantic.dataclasses import dataclass

from a_domain.types.enums import SettingsAction, SettingsFile

type Revision = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
"""A settings file's SHA-256: any edit, by the Web or by another editor, changes it."""


@dataclass(frozen=True)
class SettingsDocument:
    """One settings file as it is on disk."""

    file: SettingsFile
    text: str
    revision: Revision
    modified_at: datetime


@dataclass(frozen=True)
class SettingsBackup:
    """A copy of a settings file taken right before a save replaced it."""

    backup_id: Annotated[str, Field(pattern=r"^[0-9]{8}T[0-9]{6}Z-[0-9a-f]{12}$")]
    file: SettingsFile
    revision: Revision
    created_at: datetime


@dataclass(frozen=True)
class SettingsAuditEntry:
    """One save or restore: when, by which scope, from which revision to which, and the setting paths it changed. No value."""

    recorded_at: datetime
    file: SettingsFile
    action: SettingsAction
    actor: str
    from_revision: Revision
    to_revision: Revision
    settings: tuple[str, ...]


@dataclass(frozen=True)
class SettingsEdit:
    """
    A proposed text for one settings file, against the revision it was made from: the lines it changes, and why the
    app would refuse to start with it. An edit with problems is never saved; `saved` is the file once it was.
    """

    file: SettingsFile
    base_revision: Revision
    text: str
    revision: Revision
    changed: tuple[str, ...]
    diff: tuple[str, ...]
    problems: tuple[str, ...]
    values: dict[str, Any]
    restored_backup_id: str | None = None
    """The backup a restore puts back; None for a change of settings."""

    saved: SettingsDocument | None = None


class ISettingsFiles(Protocol):
    """
    The two settings files the administrator edits: read, validated as the app loads them, and replaced atomically
    with a backup and an audit entry. Only a SettingsFile can be named, so no request reaches another path.
    """

    async def read(self, file: SettingsFile) -> SettingsDocument: ...

    async def replace(self, file: SettingsFile, text: str, expected_revision: str, entry: SettingsAuditEntry) -> SettingsDocument:
        """
        Writes `text` when the file is still at `expected_revision`, after backing the old text up, and appends the
        audit entry. Raises SettingsConflictError and changes nothing when another editor saved first.
        """
        ...

    async def keep_backup(self, document: SettingsDocument) -> SettingsBackup:
        """Copies the text a save is about to replace, owner-only, and drops the backups beyond the kept count."""
        ...

    async def write(self, file: SettingsFile, text: str) -> SettingsDocument:
        """Replaces the file atomically: a temporary file in the same folder, flushed to disk, renamed over it."""
        ...

    async def record(self, entry: SettingsAuditEntry) -> None:
        """Appends the audit entry, owner-only. It holds setting paths and revisions, never a value."""
        ...

    async def backups(self, file: SettingsFile) -> list[SettingsBackup]:
        """The kept backups, newest first."""
        ...

    async def backup_text(self, file: SettingsFile, backup_id: str) -> str | None: ...

    async def audit_entries(self, limit: int) -> list[SettingsAuditEntry]:
        """The latest entries, newest first."""
        ...

    def revision_of(self, text: str) -> str: ...

    def values(self, text: str, paths: Sequence[str]) -> dict[str, Any]:
        """Each dotted path's value in the YAML text; a path the text does not set is absent."""
        ...

    def edited(self, text: str, changes: Mapping[str, Any]) -> str:
        """The YAML text with each dotted path set to its value, keeping comments, order and every other setting."""
        ...

    def problems(self, file: SettingsFile, text: str) -> list[str]:
        """Why the app would refuse to start with `text` as the file, by the startup load and trading checks: location and message."""
        ...

    def diff(self, file: SettingsFile, before: str, after: str) -> list[str]: ...
