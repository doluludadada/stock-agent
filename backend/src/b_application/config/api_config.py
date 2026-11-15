from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from a_domain.types.enums import ExecutionProvider, Feature, FeatureVisibility, Permission, SettingGroup, SettingUnit


class ApiConfig(BaseSettings):
    """Web API serving: the host names it answers and the limits of the administrator's settings editor."""

    model_config = SettingsConfigDict(env_file=(".env", "../.env"), env_file_encoding="utf-8", extra="ignore")

    allowed_hosts: Annotated[tuple[str, ...], Field(min_length=1, json_schema_extra={"operator_only": True})] = (
        "127.0.0.1",
        "localhost",
    )
    """The Host header names the API answers; any other gets 400. A reverse proxy's public host name goes here."""

    settings_file_max_bytes: Annotated[int, Field(gt=0, le=1_048_576, json_schema_extra={"operator_only": True})] = 262_144
    """The largest settings file the administrator's editor reads or writes."""

    settings_backups_kept: Annotated[int, Field(ge=1, le=500, json_schema_extra={"operator_only": True})] = 20
    """How many backups of each settings file the editor keeps; older ones are deleted."""

    settings_build_timeout_seconds: Annotated[float, Field(gt=0, le=600, json_schema_extra={"operator_only": True})] = 30
    """
    How long the app may take to start on new settings (the database and the broker login included) before a save or
    a reload of them is refused and the running settings keep serving.
    """

    settings_poll_seconds: Annotated[float, Field(gt=0, le=3600, json_schema_extra={"operator_only": True})] = 2
    """How often the Web API looks at the settings files on disk, to reload an edit made outside the app."""

    follow_schedule_poll_seconds: Annotated[
        float,
        Field(
            gt=0,
            le=3600,
            json_schema_extra={"steps": [15, 30, 60, 120, 300], "unit": SettingUnit.SECONDS, "group": SettingGroup.RANKING},
        ),
    ] = 60
    """How often the Web API looks whether a user's scheduled ranking follow is due."""

    valuation_cache_minutes: Annotated[
        float,
        Field(
            gt=0,
            le=1440,
            json_schema_extra={"steps": [5, 15, 30, 60, 180], "unit": SettingUnit.MINUTES, "group": SettingGroup.DATA_HISTORY},
        ),
    ] = 15
    """How long the Web API reuses a loaded market valuation (listings, MOPS EPS) across valuation requests."""

    world_interval_minutes: Annotated[
        float,
        Field(
            gt=0,
            le=1440,
            json_schema_extra={"steps": [15, 30, 60, 120, 180], "unit": SettingUnit.MINUTES, "group": SettingGroup.DATA_HISTORY},
        ),
    ] = 30
    """
    How often the Web API reads the world news feeds and the world indicators' tables, from its start on, and looks
    whether the day's world brief is due. A wire service's feed lists only its last few hours.
    """

    archive_interval_hours: Annotated[
        float,
        Field(
            gt=0, le=24, json_schema_extra={"steps": [1, 2, 3, 6, 12], "unit": SettingUnit.HOURS, "group": SettingGroup.DATA_HISTORY}
        ),
    ] = 3
    """
    How often the Web API saves the TWSE and TPEX open-data closes into the archive, from its start on. The OpenAPI
    serves a session for about a day, until the next session's report, so a few hours never miss one while the server
    runs. A save reads the listings as cached, so they are at most market_data.listing_cache_hours old.
    """


class FeaturesConfig(BaseModel):
    """
    Who the site shows each of its features to, from the `features` section of config/appsetting.yaml: one setting per
    Feature, named by the member's value. A file that names none of them, such as a deployment's older copy, runs on
    these defaults, which suit a live site: research for every user, and analysis runs, strategies and trading for
    administrators.
    """

    model_config = ConfigDict(use_attribute_docstrings=True)

    market_overview: FeatureVisibility = FeatureVisibility.EVERYONE
    ranking: FeatureVisibility = FeatureVisibility.EVERYONE
    stock_pages: FeatureVisibility = FeatureVisibility.EVERYONE
    watchlist: FeatureVisibility = FeatureVisibility.EVERYONE
    valuation: FeatureVisibility = FeatureVisibility.ADMINISTRATORS
    full_cycle: FeatureVisibility = FeatureVisibility.ADMINISTRATORS
    specific_stock: FeatureVisibility = FeatureVisibility.ADMINISTRATORS
    buzz: FeatureVisibility = FeatureVisibility.ADMINISTRATORS
    intraday: FeatureVisibility = FeatureVisibility.ADMINISTRATORS
    strategy_library: FeatureVisibility = FeatureVisibility.ADMINISTRATORS
    strategy_designer: FeatureVisibility = FeatureVisibility.ADMINISTRATORS
    strategy_backtest: FeatureVisibility = FeatureVisibility.ADMINISTRATORS
    mock_account: FeatureVisibility = FeatureVisibility.ADMINISTRATORS
    sinopac_account: FeatureVisibility = FeatureVisibility.ADMINISTRATORS
    """Reading the SinoPac account. It never orders, and only a user with USE_REAL_BROKER reads it."""

    sinopac_ordering: FeatureVisibility = FeatureVisibility.OFF
    """
    Ordering on SinoPac. Off, no order reaches SinoPac, whatever the environment and whoever the user is. On, it is
    never more than the gates of a real broker allow: USE_REAL_BROKER and the send-time checks still decide.
    """

    holdings: FeatureVisibility = FeatureVisibility.EVERYONE
    world: FeatureVisibility = FeatureVisibility.EVERYONE
    """The world page and the home page's world block. Off, the site also reads no world feed and writes no world brief."""

    def visibility(self, feature: Feature) -> FeatureVisibility:
        return getattr(self, feature.value)

    def ordering(self) -> dict[ExecutionProvider, FeatureVisibility]:
        """Whom the site lets order on each broker: the visibility of the broker's ordering feature."""
        return {broker: self.visibility(broker.ordering_feature) for broker in ExecutionProvider}

    def shown(self, permissions: frozenset[Permission]) -> frozenset[Feature]:
        """The features a viewer with these permissions sees; a visitor has none."""
        return frozenset(feature for feature in Feature if self.visibility(feature).shown_to(permissions))
