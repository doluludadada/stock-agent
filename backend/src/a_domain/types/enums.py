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


class SystemEnvironment(StrEnum):
    DEV = auto()
    TEST = auto()
    LIVE = auto()


class ExecutionProvider(StrEnum):
    MOCK = auto()
    SHIOAJI = auto()


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


class SettingsAction(StrEnum):
    SAVE = auto()
    RESTORE = auto()


class EditableSetting(StrEnum):
    """
    A setting the administrator may change from the Web, named by its dotted path in its file. Anything not listed
    stays read-only there: the environment, the broker and order mode, the score weights and thresholds, sizing and
    stop-loss, the history and quote freshness, database, folders, credentials and every source URL.
    """

    AI_ACTIVE_MODEL = "ai.active_model"
    AI_TEMPERATURE = "ai.temperature"
    AI_MAX_OUTPUT_TOKENS = "ai.max_output_tokens"
    AI_CONNECTION_TIMEOUT = "ai.connection_timeout"
    AI_ARTICLE_CONTENT_LENGTH = "ai.article_content_length"
    AI_MODEL_OPENAI = "ai.available_models.openai"
    AI_MODEL_GROK = "ai.available_models.grok"
    AI_MODEL_GEMINI = "ai.available_models.gemini"
    AI_MODEL_GROQ = "ai.available_models.groq"
    AI_MODEL_NVIDIA = "ai.available_models.nvidia"
    AI_MODEL_CLAUDE = "ai.available_models.claude"
    BEHAVIOR_LOG_LEVEL = "behavior.log_level"
    BEHAVIOR_ENABLE_WEB_SEARCH = "behavior.enable_web_search"
    BEHAVIOR_WEB_SEARCH_MAX_RESULTS = "behavior.web_search_max_results"
    ANALYSIS_REASON_ITEM_LIMIT = "analysis.reason_item_limit"
    ANALYSIS_ARTICLE_FETCH_LIMIT = "analysis.article_fetch_limit"
    ANALYSIS_LOOKBACK_DAYS = "analysis.lookback_days"
    ANALYSIS_HISTORY_CALENDAR_DAYS_PER_BAR = "analysis.history_calendar_days_per_bar"
    SENTIMENT_MIN_CONFIDENCE = "sentiment.min_confidence"
    SENTIMENT_MIN_OPINIONS = "sentiment.min_opinions"
    SENTIMENT_CONSENSUS_SHARE = "sentiment.consensus_share"
    COLLECT_BUZZ_MIN_MENTIONS = "collect_rules.buzz_min_mentions"
    COLLECT_BUZZ_MIN_ENGAGEMENT = "collect_rules.buzz_min_engagement"
    COLLECT_SOCIAL_ARTICLE_LIMIT = "collect_rules.social_article_limit"
    COLLECT_PTT_LOOKBACK_DAYS = "collect_rules.ptt_lookback_days"
    COLLECT_SPAM_KEYWORDS = "collect_rules.spam_keywords"
    COLLECT_FINANCIAL_KEYWORDS = "collect_rules.financial_keywords"
    COLLECT_PTT_TAGS = "collect_rules.ptt_tags"
    QUALITY_MIN_CHARS_STOCK = "quality.min_chars_stock"
    QUALITY_MIN_CHARS_NEWS = "quality.min_chars_news"
    QUALITY_MIN_CHARS_GOSSIP = "quality.min_chars_gossip"
    FRESHNESS_MISSING_SESSION_LISTED_STOCKS = "freshness.missing_session_listed_stocks"
    FRESHNESS_DAILY_CLOSE_MAX_MISSED_SESSIONS = "freshness.daily_close_max_missed_sessions"
    VALUATION_SCENARIO_SPREAD = "valuation.scenario_spread"
    VALUATION_MAX_SCAN_EXPLANATIONS = "valuation.max_scan_explanations"
    WATCHLIST_AUTOMATIC_EXPIRY_SESSIONS = "watchlist.automatic_expiry_sessions"
    MARKET_DATA_SEARCH_RESULT_LIMIT = "market_data.search_result_limit"
    MARKET_DATA_MOST_TRADED_COUNT = "market_data.most_traded_count"
    SYSTEM_PROMPT = "system_prompt"
    RAG_INJECTION_PROMPT = "rag_injection_prompt"
    ANALYSIS_REPORT_PROMPT_FUNDAMENTAL = "ai_analysis_report_prompt_fundamental"
    ANALYSIS_REPORT_PROMPT_MOMENTUM = "ai_analysis_report_prompt_momentum"
    SOCIAL_SENTIMENT_PROMPT = "social_sentiment_prompt"
    VALUATION_EXPLANATION_PROMPT = "ai_valuation_explanation_prompt"

    @property
    def file(self) -> SettingsFile:
        return SettingsFile.APPSETTING if "." in self.value else SettingsFile.INSTRUCTIONS

    @property
    def choices(self) -> tuple[str, ...]:
        """The values a choice setting accepts; empty for a free value that the file's validation bounds."""
        match self:
            case EditableSetting.AI_ACTIVE_MODEL:
                return tuple(provider.value for provider in AiProvider)
            case EditableSetting.BEHAVIOR_LOG_LEVEL:
                return ("DEBUG", "INFO", "WARNING", "ERROR")
            case _:
                return ()


class LockedSetting(StrEnum):
    """
    Settings the Web shows but never changes: they choose the broker, real orders, sizing and the order gates. The
    score weights choose automatic orders as surely as the thresholds they are compared with, and the daily history's
    freshness decides which stocks a run analyses at all.
    """

    ENVIRONMENT = "environment"
    EXECUTION_PROVIDER = "trading.execution_provider"
    ORDER_MODE = "trading.order_mode"
    SHIOAJI_SIMULATION = "shioaji.simulation"
    DATABASE_BACKEND = "db.backend"
    MIN_COMBINED_SCORE_BUY = "analysis.min_combined_score_buy"
    MAX_COMBINED_SCORE_SELL = "analysis.max_combined_score_sell"
    TECHNICAL_WEIGHT = "analysis.technical_weight"
    AI_WEIGHT = "analysis.ai_weight"
    RISK_PER_TRADE_PCT = "analysis.risk_per_trade_pct"
    STOP_LOSS_PCT = "analysis.stop_loss_pct"
    LOT_SIZE = "analysis.lot_size"
    REALTIME_MAX_LAG_MINUTES = "freshness.realtime_max_lag_minutes"
    HISTORY_MAX_LAG_DAYS = "freshness.history_max_lag_days"
