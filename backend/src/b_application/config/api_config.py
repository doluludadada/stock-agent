from typing import Annotated

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ApiConfig(BaseSettings):
    """Web API serving: the host names it answers and the limits of the administrator's settings editor."""

    model_config = SettingsConfigDict(env_file=(".env", "../.env"), env_file_encoding="utf-8", extra="ignore")

    allowed_hosts: Annotated[tuple[str, ...], Field(min_length=1)] = ("127.0.0.1", "localhost")
    """The Host header names the API answers; any other gets 400. A reverse proxy's public host name goes here."""

    settings_file_max_bytes: Annotated[int, Field(gt=0, le=1_048_576)] = 262_144
    """The largest settings file the administrator's editor reads or writes."""

    settings_backups_kept: Annotated[int, Field(ge=1, le=500)] = 20
    """How many backups of each settings file the editor keeps; older ones are deleted."""

    settings_build_timeout_seconds: Annotated[float, Field(gt=0, le=600)] = 30
    """
    How long the app may take to start on new settings (the database and the broker login included) before a save or
    a reload of them is refused and the running settings keep serving.
    """

    settings_poll_seconds: Annotated[float, Field(gt=0, le=3600)] = 2
    """How often the Web API looks at the settings files on disk, to reload an edit made outside the app."""

    valuation_cache_minutes: Annotated[float, Field(gt=0, le=1440)] = 15
    """How long the Web API reuses a loaded market valuation (listings, MOPS EPS) across valuation requests."""
