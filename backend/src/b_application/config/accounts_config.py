from datetime import timedelta
from typing import Annotated

from pydantic import Field, JsonValue, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from a_domain.rules.system.attempt_limit import AttemptLimitRule
from a_domain.rules.system.google_sign_in import FlowReturnRule, GoogleAccessRule, IdTokenRule
from a_domain.types.enums import SettingUnit
from a_domain.types.values import EmailAddress, comparable_name

GOOGLE_ADDRESS: dict[str, JsonValue] = {"without": "the site offers no sign-in with Google", "operator_only": True}


class AccountsConfig(BaseSettings):
    """
    What the user accounts allow, from the `accounts` section of config/appsetting.yaml; the administrator changes them
    in the settings editor, and a save applies them at once. The key never comes from the database or a settings file.
    A file that lacks a setting of sign-in with Google, such as a deployment's older copy, starts: each runs on its
    default, and the site offers no sign-in with Google while it lacks one of Google's addresses, which have no default
    because no address is written in code.
    """

    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"), env_file_encoding="utf-8", extra="ignore", env_prefix="ACCOUNTS_", use_attribute_docstrings=True
    )

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
    """
    Anyone may register as a user while an administrator exists. Never on an installation with a real broker: prod
    refuses to start with it on.
    """

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
    Wrong passwords an administrator may re-enter to save the settings from one client address in the sign-in window
    before the next is refused (429). Counted apart from the sign-ins, so neither locks the other out.
    """

    session_days: Annotated[int, Field(gt=0, le=90)]
    """How long a Web sign-in lasts. Fixed from the sign-in: a request never extends it."""

    max_concurrent_runs: Annotated[int, Field(gt=0, le=50)]
    """Workflow runs the Web API runs at once, every user's together, beside the one run per user."""

    max_concurrent_backtests: Annotated[int, Field(gt=0, le=50)]
    """
    Strategy backtests and ranking backtests the Web API replays at once, every user's together. One more waits its
    turn. Each replay holds years of daily history in memory and a core, so the server's memory and cores bound it.
    """

    max_backtests_per_user: Annotated[int, Field(gt=0, le=50)]
    """
    Strategy backtests and ranking backtests one user may have replaying or waiting before the next is refused (429).
    The ranking page asks for two at once.
    """

    saved_backtests: Annotated[int, Field(gt=0, le=200)]
    """Backtests kept per user, to compare them. Saving one more deletes the user's oldest."""

    google_client_id: str | None = Field(default=None, validation_alias="GOOGLE_CLIENT_ID")
    """GOOGLE_CLIENT_ID from the environment or .env: the OAuth client of the site in Google Cloud Console."""

    google_client_secret: SecretStr | None = Field(default=None, validation_alias="GOOGLE_CLIENT_SECRET")
    """GOOGLE_CLIENT_SECRET from the environment or .env. The site offers sign-in with Google with both and public_origin."""

    public_origin: Annotated[
        str, Field(pattern=r"^(https?://[A-Za-z0-9.-]+(:\d{1,5})?)?$", json_schema_extra={"operator_only": True})
    ] = ""
    """
    The address the browser reaches the site at: the scheme and the host, such as the https address of the server's
    Tailscale name, without a path or a trailing slash. It is https, or http on localhost or 127.0.0.1 only. Google
    sends the browser back to its /v1/auth/google/callback, which never comes from a request's Host header. Empty: no
    sign-in with Google.
    """

    google_administrator_emails: tuple[EmailAddress, ...] = ()
    """
    Google accounts that sign in as administrators, by their whole email in any case. The first sign-in creates the
    account, on an installation with no user yet too, or makes the account with that email an administrator.
    """

    google_allowed_emails: tuple[EmailAddress, ...] = ()
    """
    Google accounts that sign in as users, by their whole email in any case, whether registration is open or not. An
    email on neither list signs in with Google only while registration_open is true.
    """

    google_issuer: Annotated[str, Field(pattern=r"^(https?://\S+)?$", json_schema_extra=GOOGLE_ADDRESS)] = ""
    """
    Who must have issued an ID token, with or without the scheme, as Google writes both. Empty, like either address
    below: no sign-in with Google. `without` says what the site goes without while a file does not set the setting,
    which the start names (settings_notices).
    """

    google_authorization_endpoint: Annotated[str, Field(pattern=r"^(https?://\S+)?$", json_schema_extra=GOOGLE_ADDRESS)] = ""
    """Where the browser goes to sign in."""

    google_token_endpoint: Annotated[str, Field(pattern=r"^(https?://\S+)?$", json_schema_extra=GOOGLE_ADDRESS)] = ""
    """
    Where the server exchanges the code for the ID token. The app trusts the ID token because this connection is TLS
    to Google and carries the client secret, so it must be https, or http on localhost or 127.0.0.1 for a test.
    """

    google_timeout_seconds: Annotated[
        float, Field(gt=0, le=60, json_schema_extra={"steps": [5, 10, 15, 30, 60], "unit": SettingUnit.SECONDS})
    ] = 10
    """How long the token endpoint may take to answer."""

    google_flow_minutes: Annotated[
        int, Field(gt=0, le=60, json_schema_extra={"steps": [5, 10, 15, 30, 60], "unit": SettingUnit.MINUTES})
    ] = 10
    """How long a browser may take at Google between the start of a sign-in and its return."""

    google_fresh_authentication_seconds: Annotated[
        int, Field(gt=0, le=3600, json_schema_extra={"steps": [60, 120, 300, 600, 900, 1800, 3600], "unit": SettingUnit.SECONDS})
    ] = 300
    """
    How old the Google authentication behind a settings confirmation may be, and how long the confirmation then waits
    for its save. An administrator without a password confirms a save of the settings this way.
    """

    google_clock_skew_seconds: Annotated[
        int, Field(ge=0, le=300, json_schema_extra={"steps": [0, 10, 30, 60, 120, 300], "unit": SettingUnit.SECONDS})
    ] = 30
    """How far Google's clock and the server's may differ when an ID token's times are checked."""

    @property
    def google_sign_in(self) -> bool:
        """
        Whether the site offers sign-in with Google: the client id, the client secret, the public origin and Google's
        three addresses are all set.
        """
        addresses = (self.google_issuer, self.google_authorization_endpoint, self.google_token_endpoint)
        return bool(self.google_client_id and self.google_client_secret and self.public_origin and all(addresses))

    @property
    def google_redirect_uri(self) -> str:
        """The one redirect URI the OAuth client authorizes."""
        return f"{self.public_origin}/v1/auth/google/callback"

    def google_access_rule(self) -> GoogleAccessRule:
        return GoogleAccessRule(
            administrator_emails=frozenset(comparable_name(email) for email in self.google_administrator_emails),
            allowed_emails=frozenset(comparable_name(email) for email in self.google_allowed_emails),
            registration_open=self.registration_open,
        )

    def flow_return_rule(self) -> FlowReturnRule:
        return FlowReturnRule(offered=self.google_sign_in)

    def id_token_rule(self) -> IdTokenRule:
        return IdTokenRule(
            issuers=frozenset({self.google_issuer, self.google_issuer.partition("://")[2]}),
            client_id=self.google_client_id or "",
            clock_skew=timedelta(seconds=self.google_clock_skew_seconds),
            fresh_authentication=timedelta(seconds=self.google_fresh_authentication_seconds),
        )

    def google_sign_in_limit(self) -> AttemptLimitRule:
        """Starts and returns together, at the sign-in limit per client: a sign-in that succeeds takes its two back."""
        return self.sign_in_client_limit()

    def sign_in_name_limit(self) -> AttemptLimitRule:
        """Per name and client, so a stranger's guesses never lock the administrator out from another address."""
        return AttemptLimitRule(max_attempts=self.sign_in_failures_per_name, window=timedelta(minutes=self.sign_in_window_minutes))

    def sign_in_client_limit(self) -> AttemptLimitRule:
        return AttemptLimitRule(max_attempts=self.sign_in_failures_per_client, window=timedelta(minutes=self.sign_in_window_minutes))

    def settings_password_limit(self) -> AttemptLimitRule:
        return AttemptLimitRule(max_attempts=self.settings_password_failures, window=timedelta(minutes=self.sign_in_window_minutes))

    def registration_limit(self) -> AttemptLimitRule:
        return AttemptLimitRule(max_attempts=self.registrations_per_client, window=timedelta(minutes=self.registration_window_minutes))

    @field_validator("key", "google_client_id", "google_client_secret", mode="before")
    @classmethod
    def _blank_is_unset(cls, value: object) -> object:
        return None if isinstance(value, str) and not value.strip() else value
