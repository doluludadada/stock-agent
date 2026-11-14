from collections.abc import Mapping
from datetime import datetime
from typing import Annotated, Protocol, override

from pydantic import Field, JsonValue
from pydantic.dataclasses import dataclass

from a_domain.types.enums import (
    Audience,
    ExecutionProvider,
    FeatureVisibility,
    SettingGroup,
    SettingKind,
    SettingsAction,
    SettingsFile,
    SettingUnit,
    SystemEnvironment,
)
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
    """The setting's dotted path, such as trading.max_order_value."""

    line: Annotated[int, Field(ge=1)] | None = None
    column: Annotated[int, Field(ge=1)] | None = None
    code: str | None = None
    """
    The refusal's stable name, for a client to word it in its own language: pydantic's error type, such as
    greater_than, or the app's own, such as ai_key_missing. None for the app's other refusals, worded only in `message`.
    """

    params: dict[str, str | int | float] = Field(default_factory=dict)
    """The values the code's words need, by name, such as gt, expected or provider: the schema's or the app's, never the input."""

    @override
    def __str__(self) -> str:
        """`appsetting.yaml line 207, column 15, trading.max_order_value: Input should be ...`: how startup and the CLI print it."""
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
    One save: when, by which administrator (their user id: the audit file is plain text, and the username is stored only
    encrypted), from which revision to which, and the setting paths it changed. No value.
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
    A new text of one settings file, the settings form's changes written into the file as it is on disk, and the
    settings it changes, by dotted path. `saved` is the file once it was saved.
    """

    file: SettingsFile
    base_revision: Revision
    """The revision on disk the changes were written into."""

    text: str
    revision: Revision
    changed: tuple[str, ...]
    saved: SettingsDocument | None = None


@dataclass(frozen=True)
class SettingField:
    """
    One setting as the administrator's settings form shows it: its dotted settings path, such as ai.temperature, or an
    AI prompt's, such as ai.system_prompt; the control it gets and the group it shows under; the value the file sets,
    as JSON, else its default, else null; and what the control offers, all from the settings classes. A value the file
    sets that is none of the options or steps still shows, and stays until the administrator picks another.
    """

    path: Annotated[str, Field(min_length=1)]
    kind: SettingKind
    group: SettingGroup
    value: JsonValue
    options: tuple[str, ...] = ()
    """What a CHOICE picks one of and CHOICES any of."""

    steps: tuple[float, ...] = ()
    """The numbers STEPS picks from, rising."""

    minimum: float | None = None
    """The least number RANGE reaches, itself allowed. None where the settings name no lower bound."""

    maximum: float | None = None
    step: float | None = None
    """How far one move of RANGE goes."""

    unit: SettingUnit | None = None
    nullable: bool = False
    """The setting may be unset (null), which the form offers beside the values."""

    restart_only: bool = False
    """The setting applies only at a restart, so the form shows it and a save refuses to change it."""


@dataclass(frozen=True)
class SettingChange:
    """One setting the settings form changes: the path of its field, and its new value as JSON."""

    path: Annotated[str, Field(min_length=1)]
    value: JsonValue

    @property
    def turns_ordering_off(self) -> bool:
        """Whether it sets a broker's ordering feature to off: the change a save writes first, whatever becomes of the rest."""
        ordering = {f"features.{broker.ordering_feature.value}" for broker in ExecutionProvider}
        return self.path in ordering and self.value == FeatureVisibility.OFF.value


class ISettingsFiles(Protocol):
    """
    The YAML files of config/ the settings form writes into: read, checked as the app starts, and replaced atomically
    with a backup and an audit entry. Only a SettingsFile can be named, so no request reaches another path.
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

    def built_in_strategy_ids(self) -> list[str]:
        """The ids of the built-in strategies config/strategies/ holds, sorted: one <id>.json each."""
        ...

    def check(
        self, candidates: Mapping[SettingsFile, str], environment: SystemEnvironment, audience: Audience, host: str
    ) -> tuple[SettingsProblem, ...]:
        """
        The candidate texts, every other settings file as it is on disk, through the checks startup runs before it opens
        anything: the settings load, the trading setup, the accounts key and the active AI provider's key, and the
        environment and the audience the running process started in, which a save cannot change. The new settings must
        also keep the editor open to the administrator saving them, who reached it at `host`. Why the app would refuse
        them, or no problem.
        """
        ...
