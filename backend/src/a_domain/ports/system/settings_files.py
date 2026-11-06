from datetime import datetime
from typing import Annotated, Any, Protocol, override

from pydantic import Field
from pydantic.dataclasses import dataclass

from a_domain.types.enums import Audience, SettingsAction, SettingsFile, SystemEnvironment
from a_domain.types.ids import UserId

type Revision = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
"""A settings file's SHA-256: any edit, by the Web or by another editor, changes it."""


@dataclass(frozen=True)
class SettingsProblem:
    """
    One reason the app would not start with the settings: what, and where when a settings file names a place. The
    line and column are 1-based and point at the key the problem is about, or the YAML parser's mark. Never a value:
    pydantic's own text can quote the input, which can be a secret from .env.
    """

    message: Annotated[str, Field(min_length=1)]
    file: SettingsFile | None = None
    """None for a problem no settings file sets: a value from .env, a built-in strategy's JSON, the database or broker."""

    path: str | None = None
    """The setting's dotted path, such as trading.order_mode."""

    line: Annotated[int, Field(ge=1)] | None = None
    column: Annotated[int, Field(ge=1)] | None = None

    @override
    def __str__(self) -> str:
        """`appsetting.yaml line 207, column 15, trading.order_mode: Input should be ...`: how startup and the CLI print it."""
        place = f"{self.file.file_name} line {self.line}, column {self.column}" if self.file and self.line else None
        where = ", ".join(part for part in (place, self.path) if part)
        return f"{where}: {self.message}" if where else self.message


@dataclass(frozen=True)
class SettingsDocument:
    """One settings file as it is on disk."""

    file: SettingsFile
    text: str
    revision: Revision
    modified_at: datetime


type BackupId = Annotated[str, Field(pattern=r"^[0-9]{8}T[0-9]{6}Z-[0-9a-f]{12}$")]
"""A kept backup's name: when it was taken, in UTC, and a random part."""


@dataclass(frozen=True)
class SettingsBackup:
    """A copy of a settings file taken right before a save replaced it."""

    backup_id: BackupId
    file: SettingsFile
    revision: Revision
    created_at: datetime


@dataclass(frozen=True)
class SettingsAuditEntry:
    """
    One save or restore: when, by which administrator (their user id: the audit file is plain text, and the username
    is stored only encrypted), from which revision to which, and the setting paths it changed. No value.
    """

    recorded_at: datetime
    file: SettingsFile
    action: SettingsAction
    actor: UserId
    from_revision: Revision
    to_revision: Revision
    settings: tuple[str, ...]


@dataclass(frozen=True)
class SettingsEdit:
    """
    A proposed whole text for one settings file, written by the administrator or taken from a kept backup, against the
    file as it is on disk: the lines and settings it changes, and why the app would refuse to start with it. An edit
    with problems is never saved; `saved` is the file once it was.
    """

    file: SettingsFile
    base_revision: Revision
    """The revision on disk the edit was compared with: the one the administrator read."""

    text: str
    revision: Revision
    changed: tuple[str, ...]
    diff: tuple[str, ...]
    problems: tuple[SettingsProblem, ...]
    restored_backup_id: BackupId | None = None
    """The backup a restore puts back; None for an edited text."""

    saved: SettingsDocument | None = None

    @property
    def unchanged(self) -> bool:
        """The text is the file as it is: a save of it writes nothing."""
        return self.revision == self.base_revision


type SettingValue = bool | int | float | str | list[str]
"""What the settings form writes into one setting: a switch, a number, a text or a choice, or a list of choices."""


@dataclass(frozen=True)
class SettingChange:
    """One setting the settings form writes: its keys from the top of the file, and its new value."""

    path: Annotated[tuple[Annotated[str, Field(min_length=1)], ...], Field(min_length=1)]
    value: SettingValue


@dataclass(frozen=True)
class SettingsForm:
    """
    A text of appsetting.yaml as the settings form shows it: the text; every setting it sets, by dotted path, a list
    counting as one value (None for a text that does not parse); and the JSON schema of what each setting accepts.
    """

    text: str
    values: dict[str, Any] | None
    schema: dict[str, Any]


class ISettingsFiles(Protocol):
    """
    The YAML files of config/ the administrator edits as whole texts: read, checked as the app starts, and replaced
    atomically with a backup and an audit entry. Only a SettingsFile can be named, so no request reaches another path.
    """

    async def read(self, file: SettingsFile) -> SettingsDocument:
        """SettingsFileMissing when it is not there; SettingsFileRefused for a symlink, a file outside config/ or too large."""
        ...

    async def replace(self, file: SettingsFile, text: str, expected_revision: str, entry: SettingsAuditEntry) -> SettingsDocument:
        """
        Writes `text` when the file is still at `expected_revision`, after backing the old text up and appending the
        audit entry: a save that could not be audited is not written. Raises SettingsConflictError and changes nothing
        when another editor saved first.
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

    def leaves(self, file: SettingsFile, text: str) -> dict[str, Any] | None:
        """
        Every setting the YAML text of `file` sets, by dotted path, a list counting as one value; None for a text that does
        not parse, holds an anchor or an alias, or is not a mapping.
        """
        ...

    def check(
        self, file: SettingsFile, text: str, environment: SystemEnvironment, audience: Audience, host: str
    ) -> tuple[SettingsProblem, ...]:
        """
        `text` as `file`, with every other settings file as it is on disk, through the checks startup runs before it
        opens anything: the settings load, the trading setup, the accounts key and the active AI provider's key, and
        the environment and the audience the running process started in, which a save cannot change. The new settings
        must also keep the editor open to the administrator saving them, who reached it at `host`. Why the app would
        refuse it, or no problem.
        """
        ...

    def diff(self, file: SettingsFile, before: str, after: str) -> list[str]: ...
