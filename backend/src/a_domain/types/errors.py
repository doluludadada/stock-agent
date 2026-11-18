from datetime import datetime
from typing import Literal

from a_domain.types.enums import GoogleRefusal


class IllegalOrderTransition(ValueError):
    pass


class AiReportParseError(ValueError):
    """The model response holds no usable report or classification, so the stock gets no AI score or sentiment."""


class TechnicalSettingsConflictError(RuntimeError):
    """The owner's technical settings changed after the caller read them. Read them again before saving."""


class ListingUnavailableError(RuntimeError):
    """The exchange listing could not be loaded, so no stock can be found in it. It is not an empty market."""


class SettingsConflictError(RuntimeError):
    """The settings changed after the caller read them: a reload, or another save that wrote a file first. Read them again."""


class SettingsEditError(ValueError):
    """A change the settings form cannot write in place, or a file larger than the editor takes. Nothing was written. 422."""


class SettingsFileRefused(PermissionError):
    """The settings file is a symlink, lies outside config/ or is too large: the editor never follows or reads it. 403."""


class SettingsFileMissing(FileNotFoundError):
    """The settings file is not there. 404, said in words: the error never names a server path."""


class PasswordRequired(PermissionError):
    """A save of the settings came without the administrator's password. Nothing was written. 403."""


class PasswordRefused(PermissionError):
    """The password re-entered for a settings save is not the administrator's. Counted toward its limit; the session stays. 403."""


class GoogleConfirmationRequired(PermissionError):
    """
    A save of the settings by an administrator without a password came without a fresh Google authentication made for
    it, or with one already used or expired. Nothing was written. 403.
    """


class IdentityProviderError(RuntimeError):
    """
    The identity provider's token endpoint refused the code, did not answer, or answered no ID token the app can read.
    The message carries no token, code or secret.
    """


class GoogleSignInRefused(PermissionError):
    """A sign-in with Google, or a settings confirmation by one, that the app refused. The browser goes back to the app with it."""

    def __init__(self, refusal: GoogleRefusal) -> None:
        super().__init__(f"Google sign-in refused: {refusal.label}.")
        self.refusal = refusal


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
    """A user without USE_REAL_BROKER asked for a Pipeline on a real broker. The Web answers 403; the CLI never offers one."""


class BrokerUnavailable(LookupError):
    """A real broker that has no login up on this site now, or that the site's audience does not offer. The Web answers 403."""


class BrokerNotAnswering(RuntimeError):
    """
    A request of a real broker's SDK on an up login failed: the server did not answer in time, or answered an error
    instead. The message says the error's type and the server's status, never its words. A RuntimeError, so whatever
    takes a failed broker call in its stride, such as an order that fails, takes this one too. The Web answers 503.
    """


class RealtimeQuotesUnavailable(PermissionError):
    """
    The deployment uses open data only (audience public), which has no realtime quote, or it has no Shioaji login, and
    every order is priced on one. The open-data archive, which also answers the quotes of a personal site without a
    Shioaji login, raises it when asked for a quote. On a public site the Web answers it with 403 before Buzz or Intraday
    starts, and the CLI refuses those menus with the same code.
    """


class MopsUnavailable(PermissionError):
    """
    The deployment uses open data only (audience public), which reads no MOPS income statement, and the valuation needs
    their EPS. The Web answers it with 403 before any valuation endpoint runs, and the CLI refuses menus 5 and 6 with
    the same code.
    """


class RegistrationClosed(PermissionError):
    """Registration is switched off, or no administrator is set up yet. 403."""


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


class BacktestPeriodUnavailable(ValueError):
    """A backtest was asked over sessions the daily history cannot replay. The message says which sessions it can. 422."""


class ArchiveSaveRefused(RuntimeError):
    """The database refused some of the open-data archive's tables a save held rows for. The message names them; the rest are saved."""


class RankingUnavailable(LookupError):
    """The daily history holds no decision session of the monthly ranking. The message says what it holds. 422."""


class FeatureHidden(PermissionError):
    """The site does not show this viewer a feature the request needs (features.* in appsetting.yaml). 403: the session stays."""


class FollowTimeNotOffered(ValueError):
    """A user chose a time for the scheduled ranking follow that ranking.follow_times does not offer. Nothing saved. 422."""


class FollowBrokerNotOffered(PermissionError):
    """
    A user chose as their follow account one the site does not offer them now, or a schedule on one it does not offer.
    The message names the ones it offers. Nothing saved. 403.
    """


class FollowAccountChanged(LookupError):
    """
    A ranking follow would order on another account than the user's follow account as saved now: the account the user
    confirmed, or the one its run started on, is no longer it. Nothing is read and nothing sent. 409.
    """


class BrokerServerChanged(LookupError):
    """
    A run would order on a real broker whose login is on another server than the one the user confirmed: the server
    was switched after the page showed it. Nothing started. 409.
    """


class UnknownRankingFormula(LookupError):
    """A ranking formula was named that ranking.formulas does not hold. The message names the ones it holds."""


class AiAllowanceSpentError(RuntimeError):
    """
    Today's paid AI calls are spent, the user's or every user's together. Every AI caller of a run already treats a
    failed call as a missing AI result: AiAnalyser records a run error and the stock gets no AI score, so no automatic
    BUY; ValuationExplainer returns the sections without AI text; SentimentAnalyser records an error. The stock brief
    lets it through, so the page says the allowance is spent. 429.
    """


class BriefLimitReached(RuntimeError):
    """stock_page.brief.daily_stocks stocks got a new AI brief today, so no other stock gets one until midnight Taiwan time. 429."""


class IllegalBriefTransition(RuntimeError):
    """A stock brief was moved to a status its current status does not allow. A programming error."""
