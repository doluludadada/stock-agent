from datetime import timedelta
from typing import Annotated

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from a_domain.rules.system.attempt_limit import AttemptLimitRule


class AccountsConfig(BaseSettings):
    """
    What the user accounts allow, from the `accounts` section of config/appsetting.yaml; the administrator changes them
    in the settings editor, and a save applies them at once. The key never comes from the database or a settings file.
    """

    model_config = SettingsConfigDict(env_file=(".env", "../.env"), env_file_encoding="utf-8", extra="ignore", env_prefix="ACCOUNTS_")

    key: SecretStr | None = Field(default=None, validation_alias="ACCOUNTS_KEY")
    """
    ACCOUNTS_KEY from the environment or .env, for Docker or production: 32 random bytes, base64url. Unset or blank,
    the app reads secrets/accounts.key under the project root instead, and creates it on the first start. Everything
    that reads the saved usernames and emails derives from the key: without the same key no one can sign in again.
    """

    daily_ai_calls: Annotated[int, Field(gt=0, le=10_000)]
    """
    Paid AI calls a user (not an administrator) may make per Taiwan calendar day: stock analyses, valuation
    explanations and Buzz sentiment, every workflow counted. Past it the call is refused like a vendor's limit.
    """

    daily_ai_calls_total: Annotated[int, Field(gt=0, le=1_000_000)]
    """
    Paid AI calls of every user together per Taiwan calendar day, so the limit above does not multiply with
    registrations. An administrator's calls count toward it and are never refused by it.
    """

    registration_open: bool
    """Anyone may register as a user while an administrator exists. Never on an installation with a real broker."""

    sign_in_failures_per_name: Annotated[int, Field(gt=0, le=1000)]
    """Failed sign-ins of one sign-in name from one client address in the window before the next is refused (429)."""

    sign_in_failures_per_client: Annotated[int, Field(gt=0, le=10_000)]
    """Failed sign-ins of any name from one client address in the window before the next is refused (429)."""

    sign_in_window_minutes: Annotated[int, Field(gt=0, le=1440)]

    registrations_per_client: Annotated[int, Field(gt=0, le=1000)]
    """Registrations from one client address in the window before the next is refused (429)."""

    registration_window_minutes: Annotated[int, Field(gt=0, le=10_080)]

    settings_password_failures: Annotated[int, Field(gt=0, le=1000)]
    """
    Wrong passwords an administrator may re-enter to save or restore a settings file from one client address in the
    sign-in window before the next is refused (429). Counted apart from the sign-ins, so neither locks the other out.
    """

    session_days: Annotated[int, Field(gt=0, le=90)]
    """How long a Web sign-in lasts. Fixed from the sign-in: a request never extends it."""

    max_concurrent_runs: Annotated[int, Field(gt=0, le=50)]
    """Workflow runs the Web API runs at once, every user's together, beside the one run per user."""

    def sign_in_name_limit(self) -> AttemptLimitRule:
        """Per name and client, so a stranger's guesses never lock the administrator out from another address."""
        return AttemptLimitRule(max_attempts=self.sign_in_failures_per_name, window=timedelta(minutes=self.sign_in_window_minutes))

    def sign_in_client_limit(self) -> AttemptLimitRule:
        return AttemptLimitRule(max_attempts=self.sign_in_failures_per_client, window=timedelta(minutes=self.sign_in_window_minutes))

    def settings_password_limit(self) -> AttemptLimitRule:
        return AttemptLimitRule(max_attempts=self.settings_password_failures, window=timedelta(minutes=self.sign_in_window_minutes))

    def registration_limit(self) -> AttemptLimitRule:
        return AttemptLimitRule(max_attempts=self.registrations_per_client, window=timedelta(minutes=self.registration_window_minutes))

    @field_validator("key", mode="before")
    @classmethod
    def _blank_is_unset(cls, value: object) -> object:
        return None if isinstance(value, str) and not value.strip() else value
