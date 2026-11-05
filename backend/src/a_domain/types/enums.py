from enum import StrEnum, auto


class AiProvider(StrEnum):
    OPENAI = auto()
    GROK = auto()
    GEMINI = auto()
    GROQ = auto()
    NVIDIA = auto()
    """NVIDIA's hosted models through its OpenAI-compatible API."""

    CLAUDE = auto()
    """Anthropic's Claude models through the Messages API."""

    @property
    def label(self) -> str:
        match self:
            case AiProvider.OPENAI:
                return "OpenAI"
            case AiProvider.NVIDIA:
                return "NVIDIA"
            case _:
                return self.value.capitalize()


class AiAnalysisFocus(StrEnum):
    """Which prompt the AI analysis uses: company fundamentals (full cycle, intraday) or short-term momentum (buzz)."""

    FUNDAMENTAL = auto()
    MOMENTUM = auto()


class MessageRole(StrEnum):
    SYSTEM = auto()
    USER = auto()
    ASSISTANT = auto()


class MarketType(StrEnum):
    TWSE = auto()
    TPEX = auto()


class MarketIndex(StrEnum):
    """A market index with a daily history. Yahoo Finance serves it under the symbol `sources.yahoo.index_symbols` names."""

    TAIEX = auto()
    """The TWSE Capitalization Weighted Stock Index."""


class SecurityKind(StrEnum):
    """What a listed code trades as. Tick sizes and the SELL transaction tax differ by kind."""

    STOCK = auto()

    ETF = auto()
    """Exchange-traded fund. Taiwan ETF codes start with 00: 0050, 00878, 006208."""

    BOND_ETF = auto()
    """An ETF that holds bonds: a 00 code ending in B, such as 00679B. It trades on the ETF tick grid."""

    @classmethod
    def of(cls, stock_id: str) -> SecurityKind:
        if not stock_id.startswith("00"):
            return cls.STOCK

        return cls.BOND_ETF if stock_id.endswith("B") else cls.ETF


class TradeAction(StrEnum):
    BUY = auto()
    SELL = auto()
    HOLD = auto()


class SignalSource(StrEnum):
    """Which decision path produced a signal."""

    COMBINED = auto()
    """DecisionRule on the composite technical + AI score (EntryRule BUY/ADD, ExitRule score SELL)."""

    STOP_LOSS = auto()
    """ExitRule stop-loss: the price fell to the stop below the position's average cost."""

    MANUAL = auto()
    """The user confirmed a manual BUY override."""


class OrderType(StrEnum):
    MARKET = auto()
    """Executes at whatever price the market gives. OrderRule never makes one, and OrderAcceptanceRule refuses it."""

    LIMIT = auto()
    """Executes at the limit price or better. OrderRule prices every order at its decision's fresh quote."""


class OrderStatus(StrEnum):
    """Order lifecycle. Each status lists the statuses that may follow it in next_statuses."""

    PENDING = auto()
    """Built by the app, not yet accepted by a broker."""

    SUBMITTED = auto()
    """Accepted and working; may hold a partial fill."""

    FILLED = auto()
    """The whole quantity executed."""

    CANCELLED = auto()
    """Stopped before the whole quantity executed (by a cancel, an IOC remainder, or a FOK kill); may hold a partial fill."""

    FAILED = auto()
    """A technical error (exception, broker unreachable), whatever state the order was in."""

    REJECTED = auto()
    """Refused by a business or validation rule before acceptance (gate refused, invalid order, insufficient cash or shares)."""

    @property
    def next_statuses(self) -> frozenset[OrderStatus]:
        """SUBMITTED to SUBMITTED is a partial fill that leaves the rest working."""
        match self:
            case OrderStatus.PENDING:
                return frozenset({OrderStatus.SUBMITTED, OrderStatus.REJECTED, OrderStatus.FAILED, OrderStatus.CANCELLED})
            case OrderStatus.SUBMITTED:
                return frozenset({OrderStatus.SUBMITTED, OrderStatus.FILLED, OrderStatus.CANCELLED, OrderStatus.FAILED})
            case _:
                return frozenset()

    @property
    def is_open(self) -> bool:
        return bool(self.next_statuses)


class RejectReason(StrEnum):
    """Why an order was REJECTED before acceptance: by the app's order gate or by the broker's pre-trade checks."""

    ORDER_MODE_DISABLED = auto()
    ORDER_MODE_MISMATCH = auto()
    MARKET_CLOSED = auto()
    STALE_PRICE = auto()
    INSUFFICIENT_CASH = auto()
    POSITION_NOT_FOUND = auto()
    INSUFFICIENT_POSITION = auto()
    UNSUPPORTED_ORDER_TYPE = auto()
    UNSUPPORTED_TIME_IN_FORCE = auto()
    BROKER_REFUSED = auto()
    """The real broker refused the order before it worked (its own checks or the exchange's); the detail quotes the broker."""


class SkipReason(StrEnum):
    """Why a stock gets no stop-loss check or no trading decision in this run. Each value is the text the log shows."""

    RISK_BLOCKED = "Risk blocked"
    """This run's stop-loss check already sold it."""

    STALE_QUOTE = "Market data is stale"
    """Its realtime quote was missing or too old when fetched."""

    NO_COMPOSITE_SCORE = "Composite score unavailable"
    NO_PRICE = "No price"

    NO_REALTIME_BAR = "Realtime bar unavailable"
    """A stop-loss SELL is priced from a realtime quote only, never from a daily close."""


class TradingPhase(StrEnum):
    """Where the exchange's trading day stands. Only CONTINUOUS trading takes the IOC orders the app sends."""

    CLOSED = auto()

    OPENING_AUCTION = auto()
    """Orders queue for the opening call auction, which takes limit ROD orders only."""

    CONTINUOUS = auto()
    """Continuous trading: limit and market orders, ROD, IOC and FOK."""

    CLOSING_AUCTION = auto()
    """Orders queue for the closing call auction, which takes limit ROD orders only."""


class TimeInForce(StrEnum):
    """How long an accepted order keeps working (Taiwan exchange terms)."""

    ROD = auto()
    """Rest of Day: the unfilled part keeps working until the session closes."""

    IOC = auto()
    """Immediate or Cancel: fill what is available now, cancel the rest. OrderRule gives it to every order."""

    FOK = auto()
    """Fill or Kill: fill the whole quantity now or cancel all of it."""


class LotKind(StrEnum):
    """How the exchange counts an order's quantity. A broker sends each kind as its own exchange order."""

    BOARD_LOT = auto()
    """Whole board lots (market.board_lot_shares shares each), traded on the regular board."""

    ODD_LOT = auto()
    """Fewer shares than one board lot, traded on the intraday odd-lot board."""


class InformationSource(StrEnum):
    TWSE_MOPS = auto()
    NEWS_MEDIA = auto()
    PTT_STOCK = auto()
    PTT_GOSSIPING = auto()
    REUNION = auto()

    @property
    def is_social(self) -> bool:
        """Public discussion boards, as opposed to news media and company filings."""
        return self in {InformationSource.PTT_STOCK, InformationSource.PTT_GOSSIPING}

    @property
    def label(self) -> str:
        match self:
            case InformationSource.TWSE_MOPS:
                return "MOPS"
            case _:
                return self.value


class SentimentLabel(StrEnum):
    """One post's stance toward its stock."""

    BULLISH = auto()
    BEARISH = auto()
    NEUTRAL = auto()
    UNCLEAR = auto()


class SentimentConsensus(StrEnum):
    """What a stock's posts say together. DISAGREEMENT is its own state and never folds into NEUTRAL."""

    BULLISH = auto()
    BEARISH = auto()
    NEUTRAL = auto()
    DISAGREEMENT = auto()
    UNCLEAR = auto()


class ContentType(StrEnum):
    FACT = auto()
    NEWS = auto()
    REPORT = auto()
    ANALYSIS = auto()
    DISCUSSION = auto()
    NOISE = auto()


class WatchlistType(StrEnum):
    TECHNICAL = auto()
    BUZZ = auto()
    MANUAL = auto()


class ShioajiCredential(StrEnum):
    """
    An environment variable a Shioaji login reads, from the process environment or .env, never from a settings file.
    SystemEnvironment.shioaji_credentials says which ones each environment reads; no environment reads another's.
    """

    API_KEY = "SHIOAJI_API_KEY"
    SECRET_KEY = "SHIOAJI_SECRET_KEY"
    CA_PATH = "SHIOAJI_CA_PATH"
    CA_PASSWORD = "SHIOAJI_CA_PASSWORD"
    PERSON_ID = "SHIOAJI_PERSON_ID"
    API_KEY_TEST = "SHIOAJI_API_KEY_TEST"
    """The paper-trading key pair, which only environment test reads."""

    SECRET_KEY_TEST = "SHIOAJI_SECRET_KEY_TEST"


class ExecutionProvider(StrEnum):
    MOCK = auto()
    SHIOAJI = auto()


class SystemEnvironment(StrEnum):
    """
    Which machine the app runs on, and with it what it may trade on. Its properties are the one table of what each
    environment allows; the trading setup check and the broker login read them, and nothing else decides by
    environment. A process takes its environment at start: neither the Web editor nor a reload changes it.
    """

    DEV = auto()
    """A developer's machine: the mock broker only, and no Shioaji credential is read."""

    TEST = auto()
    """Staging before launch: Shioaji only in simulation, with the *_TEST key pair only, or the mock broker."""

    PROD = auto()
    """The live service: Shioaji only in production, with the production credentials, or the mock broker; PostgreSQL only."""

    @property
    def brokers(self) -> frozenset[ExecutionProvider]:
        match self:
            case SystemEnvironment.DEV:
                return frozenset({ExecutionProvider.MOCK})
            case SystemEnvironment.TEST | SystemEnvironment.PROD:
                return frozenset(ExecutionProvider)

    @property
    def order_modes(self) -> frozenset[OrderMode]:
        """Only prod may send a real-money order."""
        match self:
            case SystemEnvironment.DEV | SystemEnvironment.TEST:
                return frozenset({OrderMode.MOCK_ONLY, OrderMode.DISABLED})
            case SystemEnvironment.PROD:
                return frozenset(OrderMode)

    @property
    def databases(self) -> frozenset[DatabaseBackend]:
        """Prod keeps every user's data in PostgreSQL, never in a local SQLite file."""
        match self:
            case SystemEnvironment.DEV | SystemEnvironment.TEST:
                return frozenset(DatabaseBackend)
            case SystemEnvironment.PROD:
                return frozenset({DatabaseBackend.POSTGRESQL})

    @property
    def shioaji_credentials(self) -> tuple[ShioajiCredential, ...]:
        """
        The variables a Shioaji login reads here: the API key and the secret key, and in production the CA certificate's
        path, its password and the person id. ShioajiConfig.login reads each by name.
        """
        match self:
            case SystemEnvironment.DEV:
                return ()
            case SystemEnvironment.TEST:
                return (ShioajiCredential.API_KEY_TEST, ShioajiCredential.SECRET_KEY_TEST)
            case SystemEnvironment.PROD:
                return (
                    ShioajiCredential.API_KEY,
                    ShioajiCredential.SECRET_KEY,
                    ShioajiCredential.CA_PATH,
                    ShioajiCredential.CA_PASSWORD,
                    ShioajiCredential.PERSON_ID,
                )

    @property
    def shioaji_simulation(self) -> bool:
        """Shioaji's paper-trading server, or the real account. Never configured: test is always simulation, prod never."""
        return self != SystemEnvironment.PROD

    @property
    def accounts_key_file(self) -> bool:
        """
        The accounts key may live in secrets/accounts.key, created on the first start, when ACCOUNTS_KEY is unset: dev
        and test. Prod reads ACCOUNTS_KEY only: its app folder may not survive a redeploy (a Docker container), and a
        key created there would lock every account at the next deploy.
        """
        match self:
            case SystemEnvironment.DEV | SystemEnvironment.TEST:
                return True
            case SystemEnvironment.PROD:
                return False

    @property
    def refused_credentials(self) -> tuple[ShioajiCredential, ...]:
        """
        The production credentials, wherever this environment does not read them: dev and test refuse to start while
        one is set, so the production key lives only on the production machine.
        """
        return tuple(
            credential for credential in SystemEnvironment.PROD.shioaji_credentials if credential not in self.shioaji_credentials
        )


class Workflow(StrEnum):
    """The user-facing operation a run belongs to. Each run has one run id."""

    FULL_CYCLE = auto()
    BUZZ_SCAN = auto()
    INTRADAY = auto()
    SPECIFIC_STOCKS = auto()
    MANUAL_BUY = auto()
    VALUATION = auto()
    """Menus 5 and 6. Read-only: no run record, no order."""

    RESEARCH = auto()
    """The Web stock page's technical evaluation, and the account history. Read-only: no run record, no AI call, no order."""


class OrderMode(StrEnum):
    MOCK_ONLY = auto()
    LIVE = auto()
    DISABLED = auto()


class RuleEffect(StrEnum):
    BLOCK_ON_FAIL = auto()
    REDUCE_SCORE_ON_FAIL = auto()
    INCREASE_SCORE_ON_PASS = auto()


class EpsKind(StrEnum):
    SINGLE_QUARTER = auto()
    CUMULATIVE = auto()
    ANNUAL = auto()
    TRAILING_TWELVE_MONTHS = auto()

    @property
    def label(self) -> str:
        match self:
            case EpsKind.SINGLE_QUARTER:
                return "single quarter"
            case EpsKind.CUMULATIVE:
                return "cumulative"
            case EpsKind.ANNUAL:
                return "annual"
            case EpsKind.TRAILING_TWELVE_MONTHS:
                return "TTM"


class EpsBasis(StrEnum):
    ACTUAL = auto()
    ESTIMATE = auto()

    @property
    def label(self) -> str:
        return "actual" if self == EpsBasis.ACTUAL else "estimate"


class EpsUnavailableReason(StrEnum):
    NOT_LOADED = auto()
    """The workflow did not load fundamentals for this stock."""

    NOT_REPORTED = auto()
    """No filing in any candidate quarter: an ETF, a DR, a new listing or a suspended filer."""

    INCOMPLETE_HISTORY = auto()
    """The TTM needs a prior-year filing the company does not have."""

    SOURCE_FAILED = auto()
    """A quarter the TTM needs could not be fetched."""

    @property
    def label(self) -> str:
        """What the report says after "Insufficient data", with `{quarter}` where the reason's quarter goes."""
        match self:
            case EpsUnavailableReason.NOT_LOADED:
                return "no financial statements were loaded"
            case EpsUnavailableReason.NOT_REPORTED:
                return "no filing for this code since {quarter} (an ETF, a DR, a new listing or a company that has not filed)"
            case EpsUnavailableReason.INCOMPLETE_HISTORY:
                return "the cumulative EPS for {quarter} is missing, so the TTM EPS cannot be computed"
            case EpsUnavailableReason.SOURCE_FAILED:
                return "the {quarter} filings could not be fetched"


class ScanStep(StrEnum):
    VALUATION = auto()
    TECHNICAL = auto()

    @property
    def label(self) -> str:
        return "valuation" if self == ScanStep.VALUATION else "technical"


class EliminationReason(StrEnum):
    EPS_UNAVAILABLE = auto()
    EPS_NOT_POSITIVE = auto()
    PRICE_MISSING = auto()
    PRICE_STALE = auto()
    BELOW_MIN_UNDERVALUATION = auto()
    NO_PRICE_HISTORY = auto()
    TECHNICAL_HARD_FAILURE = auto()

    @property
    def step(self) -> ScanStep:
        if self in (EliminationReason.NO_PRICE_HISTORY, EliminationReason.TECHNICAL_HARD_FAILURE):
            return ScanStep.TECHNICAL

        return ScanStep.VALUATION

    @property
    def label(self) -> str:
        match self:
            case EliminationReason.EPS_UNAVAILABLE:
                return "insufficient EPS data"
            case EliminationReason.EPS_NOT_POSITIVE:
                return "EPS ≤ 0"
            case EliminationReason.PRICE_MISSING:
                return "no valid price"
            case EliminationReason.PRICE_STALE:
                return "stale price"
            case EliminationReason.BELOW_MIN_UNDERVALUATION:
                return "undervaluation below the minimum"
            case EliminationReason.NO_PRICE_HISTORY:
                return "no usable daily history (missing or stale), so the technical strategy cannot run"
            case EliminationReason.TECHNICAL_HARD_FAILURE:
                return "technical hard failure"


class PeNotApplicableReason(StrEnum):
    EPS_UNAVAILABLE = auto()
    EPS_ZERO = auto()
    EPS_NEGATIVE = auto()
    INVALID_PRICE = auto()

    @property
    def label(self) -> str:
        match self:
            case PeNotApplicableReason.EPS_UNAVAILABLE:
                return "insufficient data"
            case PeNotApplicableReason.EPS_ZERO:
                return "cannot be computed"
            case PeNotApplicableReason.EPS_NEGATIVE:
                return "loss-making, P/E not applicable"
            case PeNotApplicableReason.INVALID_PRICE:
                return "no valid price"

    @property
    def elimination_reason(self) -> EliminationReason:
        """Why the undervalued scan's valuation step eliminates a stock whose P/E does not apply for this reason."""
        match self:
            case PeNotApplicableReason.EPS_UNAVAILABLE:
                return EliminationReason.EPS_UNAVAILABLE
            case PeNotApplicableReason.EPS_ZERO | PeNotApplicableReason.EPS_NEGATIVE:
                return EliminationReason.EPS_NOT_POSITIVE
            case PeNotApplicableReason.INVALID_PRICE:
                return EliminationReason.PRICE_MISSING


class ScenarioName(StrEnum):
    CONSERVATIVE = auto()
    BASE = auto()
    OPTIMISTIC = auto()

    @property
    def label(self) -> str:
        match self:
            case ScenarioName.CONSERVATIVE:
                return "Conservative"
            case ScenarioName.BASE:
                return "Base"
            case ScenarioName.OPTIMISTIC:
                return "Optimistic"


class DatabaseBackend(StrEnum):
    """
    The database this process writes. It is chosen in config/appsetting.yaml, never from which credentials happen to be
    set, so a service missing one PostgreSQL variable fails at startup instead of writing to a local SQLite file.
    """

    SQLITE = auto()
    POSTGRESQL = auto()


class IndicatorOutput(StrEnum):
    """One number an indicator gives. Which outputs an indicator has is IndicatorKind.outputs."""

    VALUE = auto()
    LINE = auto()
    SIGNAL = auto()
    HISTOGRAM = auto()
    UPPER = auto()
    MIDDLE = auto()
    LOWER = auto()
    BANDWIDTH = auto()
    PERCENT_B = auto()
    PERCENT_K = auto()
    PERCENT_D = auto()
    ADX = auto()
    PLUS_DI = auto()
    MINUS_DI = auto()
    MOVING_AVERAGE = auto()


class IndicatorKind(StrEnum):
    """An indicator the calculator knows. A strategy sets its parameters; its name in a rule is only a label."""

    SMA = auto()
    """Simple moving average of the daily closes."""

    VOLUME_SMA = auto()
    """Simple moving average of the daily volumes, in shares."""

    RSI = auto()
    MACD = auto()
    BOLLINGER = auto()
    STOCHASTIC = auto()
    ADX = auto()
    ATR = auto()
    OBV = auto()
    """On-balance volume, and its simple moving average over the period."""

    MFI = auto()

    @property
    def outputs(self) -> tuple[IndicatorOutput, ...]:
        match self:
            case IndicatorKind.MACD:
                return IndicatorOutput.LINE, IndicatorOutput.SIGNAL, IndicatorOutput.HISTOGRAM
            case IndicatorKind.BOLLINGER:
                return (
                    IndicatorOutput.UPPER,
                    IndicatorOutput.MIDDLE,
                    IndicatorOutput.LOWER,
                    IndicatorOutput.BANDWIDTH,
                    IndicatorOutput.PERCENT_B,
                )
            case IndicatorKind.STOCHASTIC:
                return IndicatorOutput.PERCENT_K, IndicatorOutput.PERCENT_D
            case IndicatorKind.ADX:
                return IndicatorOutput.ADX, IndicatorOutput.PLUS_DI, IndicatorOutput.MINUS_DI
            case IndicatorKind.OBV:
                return IndicatorOutput.VALUE, IndicatorOutput.MOVING_AVERAGE
            case _:
                return (IndicatorOutput.VALUE,)


class MarketField(StrEnum):
    """A field of one completed daily bar. Volume is in shares."""

    OPEN = auto()
    HIGH = auto()
    LOW = auto()
    CLOSE = auto()
    VOLUME = auto()


class FormulaNode(StrEnum):
    """The kind of one part of a technical formula; JSON names it in the part's `type` field."""

    CONSTANT = auto()
    """A plain number. JSON writes it as the number itself, with no `type`."""

    MARKET = auto()
    LATEST_PRICE = auto()
    INDICATOR = auto()
    ARITHMETIC = auto()
    COMPARISON = auto()
    GROUP = auto()


class ArithmeticOperator(StrEnum):
    ADD = auto()
    SUBTRACT = auto()
    MULTIPLY = auto()
    DIVIDE = auto()


class ComparisonOperator(StrEnum):
    GT = auto()
    GTE = auto()
    LT = auto()
    LTE = auto()
    EQ = auto()
    NE = auto()
    CROSSES_ABOVE = auto()
    """The left side was at or below the right side one daily bar earlier, and is above it now."""

    CROSSES_BELOW = auto()
    """The left side was at or above the right side one daily bar earlier, and is below it now."""

    @property
    def is_crossing(self) -> bool:
        return self in (ComparisonOperator.CROSSES_ABOVE, ComparisonOperator.CROSSES_BELOW)


class GroupOperator(StrEnum):
    ALL = auto()
    ANY = auto()


class SettingsFile(StrEnum):
    """A settings file in config/ the administrator may edit from the Web. Nothing else on disk can be named."""

    APPSETTING = auto()
    INSTRUCTIONS = auto()

    @property
    def file_name(self) -> str:
        match self:
            case SettingsFile.APPSETTING:
                return "appsetting.yaml"
            case SettingsFile.INSTRUCTIONS:
                return "instructions.yaml"


class InstructionKey(StrEnum):
    """
    A key of config/instructions.yaml: an AI prompt, and the setting load_settings copies it into. One table for the
    copy, for refusing any other key of the file, and for placing a refused prompt back on its line there.
    """

    SYSTEM_PROMPT = "system_prompt"
    RAG_INJECTION_PROMPT = "rag_injection_prompt"
    ANALYSIS_REPORT_FUNDAMENTAL = "ai_analysis_report_prompt_fundamental"
    ANALYSIS_REPORT_MOMENTUM = "ai_analysis_report_prompt_momentum"
    VALUATION_EXPLANATION = "ai_valuation_explanation_prompt"
    SOCIAL_SENTIMENT = "social_sentiment_prompt"

    @property
    def settings_path(self) -> str:
        match self:
            case InstructionKey.SYSTEM_PROMPT:
                return "ai.system_prompt"
            case InstructionKey.RAG_INJECTION_PROMPT:
                return "ai.rag_injection_prompt"
            case InstructionKey.ANALYSIS_REPORT_FUNDAMENTAL:
                return "prompts.analysis_report_fundamental"
            case InstructionKey.ANALYSIS_REPORT_MOMENTUM:
                return "prompts.analysis_report_momentum"
            case InstructionKey.VALUATION_EXPLANATION:
                return "prompts.valuation_explanation"
            case InstructionKey.SOCIAL_SENTIMENT:
                return "prompts.social_sentiment"


class SettingsAction(StrEnum):
    SAVE = auto()
    RESTORE = auto()


class ErrorCode(StrEnum):
    """
    The stable name of each refusal the Web API answers, in `code` next to `detail`: a client switches on it, never on
    the words, which may change. Every 403 has its own, so the page tells a missing password from a wrong one, a
    refused file, a user who is not an administrator and an installation on a real broker.
    """

    SIGN_IN_REQUIRED = auto()
    SIGN_IN_REFUSED = auto()
    SIGN_IN_THROTTLED = auto()
    REGISTRATION_CLOSED = auto()
    SETUP_CODE_REFUSED = auto()
    ALREADY_SET_UP = auto()
    USER_EXISTS = auto()
    LAST_ADMINISTRATOR = auto()
    UNKNOWN_HOST = auto()
    APP_REQUEST_REQUIRED = auto()
    ADMINISTRATORS_ONLY = auto()
    REAL_BROKER_REFUSED = auto()
    MOCK_BROKER_ONLY = auto()
    PASSWORD_REQUIRED = auto()
    PASSWORD_REFUSED = auto()
    SETTINGS_FILE_REFUSED = auto()
    SETTINGS_FILE_MISSING = auto()
    SETTINGS_CONFLICT = auto()
    SETTINGS_EDIT_REFUSED = auto()
    SETTINGS_REFUSED = auto()
    """The app would not start with the settings: the answer also lists `problems`, each at its file, line and column."""

    TECHNICAL_SETTINGS_CONFLICT = auto()
    RUN_IN_PROGRESS = auto()
    TOO_MANY_RUNS = auto()
    LISTING_UNAVAILABLE = auto()
    NOT_FOUND = auto()
    INVALID_REQUEST = auto()
    """The body, the path or the query does not validate: `detail` is FastAPI's list of the fields and why."""

    BODY_TOO_LARGE = auto()
    REQUEST_REFUSED = auto()
    """Any other refusal, such as the LINE webhook's: `detail` says why."""


class Permission(StrEnum):
    """
    What a role may do beyond using its own data. A signed-in user of any role runs every workflow on their own mock
    account, watchlist, records and strategies; no permission is needed for that. Each member's docstring names where
    it is checked, always against User.permissions.
    """

    MANAGE_USERS = auto()
    """List users, change a role or a password, deactivate or reactivate one: /v1/admin/users. Checked by requires()."""

    EDIT_SYSTEM_SETTINGS = auto()
    """The settings files config/appsetting.yaml and config/instructions.yaml: /v1/admin/settings*. Checked by requires()."""

    USE_CLI = auto()
    """Sign in to the CLI, the only path to manual BUY and to orders on a real broker. Checked by the CLI's sign-in."""

    USE_REAL_BROKER = auto()
    """
    Use the private pages, and own a pipeline, over the installation's real broker (Shioaji). Checked by the Web's
    private-page gate before any Pipeline is built, and again where dependencies.py picks the broker, so no Pipeline
    of another user ever holds it.
    """

    NOTIFY_RECIPIENTS = auto()
    """This user's run reports go to the installation's LINE recipients. Checked where dependencies.py builds Reporting."""

    UNCAPPED_AI = auto()
    """
    No per-user daily limit on paid AI calls (accounts.daily_ai_calls). The calls still count toward the server's daily
    total, which never refuses them. Checked where dependencies.py builds the user's AI provider.
    """

    UNCAPPED_RUNS = auto()
    """
    Start a Web run while the server runs its most at once (accounts.max_concurrent_runs), so other users' runs never
    keep an administrator from working. One run at a time per user still holds, and the run counts toward the cap
    others meet. Checked by WorkflowRuns.start.
    """


class Role(StrEnum):
    ADMINISTRATOR = auto()
    """Everything: their own data, the users and the system settings files."""

    USER = auto()
    """Everything except administration. Open registration creates this role."""

    @property
    def permissions(self) -> frozenset[Permission]:
        """The table from role to permissions. A new permission is granted here, never by a check that names a role."""
        match self:
            case Role.ADMINISTRATOR:
                return frozenset(Permission)
            case Role.USER:
                return frozenset()


class AttemptLimit(StrEnum):
    """Which limit counts a sign-in or registration attempt. Each counts per client address."""

    SIGN_IN_NAME = auto()
    """Failed sign-ins of one sign-in name from one client address."""

    SIGN_IN_CLIENT = auto()
    """Failed sign-ins of any name from one client address."""

    REGISTRATION = auto()
    """Registrations from one client address."""

    SETTINGS_PASSWORD = auto()
    """
    Passwords an administrator re-entered to save or restore a settings file, per administrator and client address.
    Its own count, so the editor cannot guess the password faster than the sign-in allows, nor lock the sign-in out.
    """


class UserStatus(StrEnum):
    ACTIVE = auto()
    """May sign in. Every session of the user is valid until it expires."""

    DEACTIVATED = auto()
    """
    May not sign in, and every session ended at the change. A run already running finishes. The user's data stays, and
    reactivation restores access.
    """
