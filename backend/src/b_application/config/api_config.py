from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class ApiConfig(BaseSettings):
    """Web API access. Every write needs `Authorization: Bearer <API_TOKEN>`; while API_TOKEN is unset or blank, writes are refused."""

    model_config = SettingsConfigDict(env_file=(".env", "../.env"), env_file_encoding="utf-8", extra="ignore")

    token: SecretStr | None = Field(default=None, validation_alias="API_TOKEN")

    @field_validator("token", mode="before")
    @classmethod
    def _blank_is_unset(cls, value: object) -> object:
        return None if isinstance(value, str) and not value.strip() else value
