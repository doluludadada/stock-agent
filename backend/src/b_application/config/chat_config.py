from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class LineConfig(BaseSettings):
    """LINE Bot credentials."""

    model_config = SettingsConfigDict(env_file=(".env", "../.env"), env_file_encoding="utf-8", extra="ignore")

    channel_id: str | None = Field(default=None, validation_alias="LINE_CHANNEL_ID")
    channel_secret: str | None = Field(default=None, validation_alias="LINE_CHANNEL_SECRET")
    channel_access_token: str | None = Field(default=None, validation_alias="LINE_CHANNEL_ACCESS_TOKEN")


class DbConfig(BaseSettings):
    """Database settings for RAG and application data: credentials from the environment, the rest from config/appsetting.yaml."""

    model_config = SettingsConfigDict(env_file=(".env", "../.env"), env_file_encoding="utf-8", extra="ignore")

    chroma_persist_path: str
    reset_commands: set[str]

    user: str | None = Field(default=None, validation_alias="DB_USER")
    password: str | None = Field(default=None, validation_alias="DB_PASSWORD")
    host: str | None = Field(default=None, validation_alias="DB_HOST")
    port: int = Field(default=5432, validation_alias="DB_PORT")
    name: str | None = Field(default=None, validation_alias="DB_NAME")


class NotificationConfig(BaseModel):
    """Notification settings."""

    enabled: bool = False
    recipients: list[str] = Field(default_factory=list)
