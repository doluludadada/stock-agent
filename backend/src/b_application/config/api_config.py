from typing import Annotated

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class ApiConfig(BaseSettings):
    """
    Web API access, with two scopes. API_TOKEN is the owner's: every write and every read of private data (runs,
    decisions, orders, the watchlist, the account, the saved technical settings). ADMIN_API_TOKEN is the
    administrator's and opens only the settings-file endpoints. Each scope is refused while its token is unset or
    blank, and the administrator scope also while its token equals API_TOKEN, so the owner's token never doubles as it.
    """

    model_config = SettingsConfigDict(env_file=(".env", "../.env"), env_file_encoding="utf-8", extra="ignore")

    token: SecretStr | None = Field(default=None, validation_alias="API_TOKEN")
    admin_token: SecretStr | None = Field(default=None, validation_alias="ADMIN_API_TOKEN")

    allowed_hosts: Annotated[tuple[str, ...], Field(min_length=1)] = ("127.0.0.1", "localhost")
    """The Host header names the API answers; any other gets 400. A reverse proxy's public host name goes here."""

    settings_file_max_bytes: Annotated[int, Field(gt=0, le=1_048_576)] = 262_144
    """The largest settings file the administrator's editor reads or writes."""

    settings_backups_kept: Annotated[int, Field(ge=1, le=500)] = 20
    """How many backups of each settings file the editor keeps; older ones are deleted."""

    valuation_cache_minutes: Annotated[float, Field(gt=0, le=1440)] = 15
    """How long the Web API reuses a loaded market valuation (listings, MOPS EPS) across valuation requests."""

    @field_validator("token", "admin_token", mode="before")
    @classmethod
    def _blank_is_unset(cls, value: object) -> object:
        return None if isinstance(value, str) and not value.strip() else value

    @property
    def admin_enabled(self) -> bool:
        if self.admin_token is None:
            return False

        return self.token is None or self.admin_token.get_secret_value() != self.token.get_secret_value()
