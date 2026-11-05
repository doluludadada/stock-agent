from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class LineConfig(BaseSettings):
    """LINE Bot credentials."""

    model_config = SettingsConfigDict(env_file=(".env", "../.env"), env_file_encoding="utf-8", extra="ignore")

    channel_id: str | None = Field(default=None, validation_alias="LINE_CHANNEL_ID")
    channel_secret: str | None = Field(default=None, validation_alias="LINE_CHANNEL_SECRET")
    channel_access_token: str | None = Field(default=None, validation_alias="LINE_CHANNEL_ACCESS_TOKEN")


class ChatConfig(BaseModel):
    """The chat's reset command. Every value comes from the `chat` section of config/appsetting.yaml."""

    reset_commands: set[str]
    """Messages that clear the conversation instead of getting an AI reply."""

    reset_reply: str
    """The chat's answer to a reset command."""


class NotificationConfig(BaseModel):
    """Notification settings."""

    enabled: bool = False
    recipients: list[str] = Field(default_factory=list)
