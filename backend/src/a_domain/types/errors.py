from datetime import datetime
from typing import Literal


class IllegalOrderTransition(ValueError):
    pass


class AiReportParseError(ValueError):
    """The model response holds no usable report or classification, so the stock gets no AI score or sentiment."""


class TechnicalSettingsConflictError(RuntimeError):
    """The owner's technical settings changed after the caller read them. Read them again before saving."""


class ListingUnavailableError(RuntimeError):
    """The exchange listing could not be loaded, so no stock can be found in it. It is not an empty market."""


class SettingsConflictError(RuntimeError):
    """The settings file changed after the caller read it: another tab or an editor saved first. Read it again."""


class SettingsEditError(ValueError):
    """The edit cannot be written as it is, such as a file larger than the editor takes. Nothing was written. 422."""


class SettingsFileRefused(PermissionError):
    """The settings file is a symlink, lies outside config/ or is too large: the editor never follows or reads it. 403."""


class SettingsFileMissing(FileNotFoundError):
    """The settings file, or the backup named, is not there. 404, said in words: the error never names a server path."""


class PasswordRequired(PermissionError):
    """A save or a restore of a settings file came without the administrator's password. Nothing was written. 403."""


class PasswordRefused(PermissionError):
    """The password re-entered for a settings save is not the administrator's. Counted toward its limit; the session stays. 403."""


class SignInRequired(PermissionError):
    """A signed-out pipeline used a port that holds a user's data. The Web answers 401."""


class SignInRefused(PermissionError):
    """A wrong username, email or password, or a deactivated user: one message for all, so it reveals no account. 401."""


class SignInThrottled(PermissionError):
    """Too many recent attempts from this sign-in name or client. The Web answers 429 with Retry-After."""

    def __init__(self, retry_at: datetime, now: datetime) -> None:
        super().__init__(f"Too many attempts. Try again after {retry_at:%H:%M %Z}.")
        self.retry_at = retry_at
        self.retry_after = retry_at - now
        """How long until the next attempt, by the clock that refused this one: the Web's Retry-After."""


class RealBrokerRefused(PermissionError):
    """A user without USE_REAL_BROKER on an installation whose broker is real. The Web answers 403; the CLI never meets it."""


class RealtimeQuotesUnavailable(PermissionError):
    """
    The deployment uses open data only (audience public), which has no realtime quote, and every order is priced on
    one. The open-data archive raises it when asked for a quote, and the Web answers it with 403 before Buzz or
    Intraday starts. The CLI refuses those menus with the same code.
    """


class MopsUnavailable(PermissionError):
    """
    The deployment uses open data only (audience public), which reads no MOPS income statement, and the valuation needs
    their EPS. The Web answers it with 403 before any valuation endpoint runs, and the CLI refuses menus 5 and 6 with
    the same code.
    """


class RegistrationClosed(PermissionError):
    """Registration is switched off, the installation trades on a real broker, or no administrator is set up yet. 403."""


class AlreadySetUpError(RuntimeError):
    """The first administrator exists: the first-time setup runs once per installation. 409."""


class UserExistsError(ValueError):
    """The username or the email is taken, compared without case. 409, naming the field."""

    def __init__(self, field: Literal["username", "email"]) -> None:
        super().__init__(f"That {field} is taken.")
        self.field = field


class LastAdministratorError(RuntimeError):
    """The change would leave no active administrator, so nothing was saved. 409."""


class AiModelNotOffered(ValueError):
    """A user chose an AI model the site does not offer, neither ai.active_model nor one of ai.user_selectable. Nothing saved. 422."""
