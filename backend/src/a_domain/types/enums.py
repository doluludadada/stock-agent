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

    @property
    def changes_from_a_moved_reference(self) -> bool:
        """
        Whether a stock's change on its first trade after a session it did not trade is from a reference the exchange
        moved to that session's last bid or ask. TPEX's is: 2064 closed at 11.80 on 2026-10-13, did not trade on
        2026-10-14 and closed at 11.70 on 2026-10-15 with a change of -0.15. TWSE writes X0.00 there instead: 1213 on
        2026-10-20. Such a change cannot tell a corporate action from that move.
        """
        match self:
            case MarketType.TPEX:
                return True
            case MarketType.TWSE:
                return False


class MarketIndex(StrEnum):
    """A market index with a daily history: the own index of the exchange `market` names, kept under that market."""

    TAIEX = auto()
    """The TWSE Capitalization Weighted Stock Index."""

    @property
    def market(self) -> MarketType:
        """The exchange that publishes it, under which the open-data archive and the exchanges' history cache keep its closes."""
        match self:
            case MarketIndex.TAIEX:
                return MarketType.TWSE


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

    FOLLOW = auto()
    """The user followed a decision another run recorded: same stock, action and shares, priced again when followed."""

    RANKING = auto()
    """
    The user's mock account followed the monthly ranking: a SELL of a holding the ranking left, or a BUY of a ranked
    stock it lacked, at an equal weight of the account.
    """


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

    @property
    def fill_final(self) -> bool:
        """
        Its filled quantity is all it will ever fill. An open order may still fill, and a FAILED one may have filled
        at the broker whatever it recorded.
        """
        return not self.is_open and self != OrderStatus.FAILED


class RejectReason(StrEnum):
    """Why an order was REJECTED before acceptance: by the app's order gate or by the broker's pre-trade checks."""

    BROKER_NOT_CHOSEN = auto()
    """The order would reach another broker than the one its run chose when it started."""

    BROKER_NOT_OFFERED = auto()
    """The site's audience or its order pricing offers no such broker: a public site orders on the mock account only."""

    ORDERING_OFF = auto()
    """The site does not let the user order on the real broker: the visibility of its ordering feature (features.*) hides it."""

    REAL_BROKER_REFUSED = auto()
    """A real broker's order of a user who is not, as saved at the send, an active administrator (USE_REAL_BROKER)."""

    BROKER_LOGIN_DOWN = auto()
    """The real broker's login failed or went down before the send."""

    BROKER_SERVER_MISMATCH = auto()
    """The real broker's login is on another server than the environment trades on (SystemEnvironment.shioaji_simulation)."""

    ORDER_VALUE_LIMIT = auto()
    """A real broker's BUY costs more than trading.max_order_value at its limit price, or has no limit price to value."""

    DAILY_BUY_LIMIT = auto()
    """A real broker's BUY would take the day's BUYs on it past trading.max_daily_buy_value."""

    MARKET_CLOSED = auto()
    SESSION_IN_PROGRESS = auto()
    """An official close prices an order only while no session trades: during one, that close is no longer the price."""

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


class OrderPricing(StrEnum):
    """
    What prices an order of this deployment, in which phase of the trading day it may be placed and on which brokers.
    Audience.order_pricing picks one; OrderGateRule and the follow's window read it, and nothing else decides by it.
    """

    REALTIME_QUOTE = auto()
    """A realtime quote at most freshness.realtime_max_lag_minutes old, in continuous trading, on any broker."""

    OFFICIAL_CLOSE = auto()
    """
    The official close of the last closed session, while no session trades, on the mock broker only: the newest price
    that exists, so a follow of an old run never buys at that run's price. Taiwan's after-hours fixed-price trading
    fills at the same close.
    """

    @property
    def trading_phase(self) -> TradingPhase:
        """The one phase in which an order priced this way may be placed."""
        match self:
            case OrderPricing.REALTIME_QUOTE:
                return TradingPhase.CONTINUOUS
            case OrderPricing.OFFICIAL_CLOSE:
                return TradingPhase.CLOSED

    @property
    def brokers(self) -> frozenset[ExecutionProvider]:
        match self:
            case OrderPricing.REALTIME_QUOTE:
                return frozenset(ExecutionProvider)
            case OrderPricing.OFFICIAL_CLOSE:
                return frozenset({ExecutionProvider.MOCK})

    @property
    def outside_phase(self) -> RejectReason:
        """Why an order placed in any other phase is refused."""
        match self:
            case OrderPricing.REALTIME_QUOTE:
                return RejectReason.MARKET_CLOSED
            case OrderPricing.OFFICIAL_CLOSE:
                return RejectReason.SESSION_IN_PROGRESS


class FollowRefusal(StrEnum):
    """
    Why a run's decisions, or the monthly ranking, cannot be followed into the user's mock account now. The Web API
    answers each as its code.
    """

    NOTHING_TO_FOLLOW = auto()
    """
    The run has no decision left to follow: it is not a finished Full Cycle, it decided no BUY and no SELL of a stock
    the account holds, or a follow order of each filled since the mock account opened. The ranking has none either: the
    account holds each of its stocks and nothing else, or it ranks no stock.
    """

    OUTSIDE_FOLLOW_WINDOW = auto()
    """The market is in a phase in which this site's order pricing places no order (OrderPricing.trading_phase)."""


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
    TWSE_NEWS = auto()
    """TWSE's own news: its listing reviews, penalties and notices of corporate actions."""

    NEWS_MEDIA = auto()
    PTT_STOCK = auto()
    PTT_GOSSIPING = auto()
    ANNUAL_REPORT = auto()
    """A section of a company's shareholders'-meeting annual report on the exchange's document site, kept as its text."""

    CNA = auto()
    """The Central News Agency's public feeds of international and financial news, in Chinese."""

    BBC = auto()
    """The BBC's public feed of business news, in English."""

    FEDERAL_RESERVE = auto()
    """The Federal Reserve Board's feed of its monetary policy press releases: a United States government work."""

    @property
    def is_world(self) -> bool:
        """
        A publisher's own feed of world news, about no one stock (MarketScope.WORLD). The site keeps of an item what
        the feed itself gives a reader: its title, its summary and its address, never the article's page.
        """
        return self in {InformationSource.CNA, InformationSource.BBC, InformationSource.FEDERAL_RESERVE}

    @property
    def is_reference(self) -> bool:
        """
        A document of record the site reads once a year, not news of a day: it is kept whatever the stock's newer
        articles, so a busy stock's news never pushes its annual report out of the article store.
        """
        return self is InformationSource.ANNUAL_REPORT

    @property
    def is_social(self) -> bool:
        """Public discussion boards, as opposed to news media and company filings."""
        return self in {InformationSource.PTT_STOCK, InformationSource.PTT_GOSSIPING}

    @property
    def is_open_data(self) -> bool:
        """
        The exchanges' open data, whose text a site may show in full under its license: a company's material information
        and TWSE's own news. A news site's or a board's text is theirs, so the stock page shows its title and links out.
        """
        return self in {InformationSource.TWSE_MOPS, InformationSource.TWSE_NEWS}

    @property
    def label(self) -> str:
        match self:
            case InformationSource.TWSE_MOPS:
                return "MOPS"
            case InformationSource.TWSE_NEWS:
                return "TWSE news"
            case InformationSource.ANNUAL_REPORT:
                return "annual report"
            case InformationSource.CNA:
                return "CNA"
            case InformationSource.BBC:
                return "BBC"
            case InformationSource.FEDERAL_RESERVE:
                return "Federal Reserve"
            case _:
                return self.value


class MarketScope(StrEnum):
    """
    What an article or a brief is about when it is about no one stock. Its value stands where a stock id stands, in
    the article store, the article index and the briefs, and no stock id can equal it.
    """

    WORLD = "#world"
    """The world outside Taiwan's exchanges: the world news feeds' items and the day's world brief."""


class WorldIndicator(StrEnum):
    """
    A figure of the world's markets the site holds one reading a day of, each from a public agency that serves it
    without a key: the Taiwan Futures Exchange's daily reference exchange rates and the United States Treasury's
    daily yields.
    """

    USD_TWD = auto()
    """New Taiwan dollars per US dollar."""

    USD_JPY = auto()
    EUR_USD = auto()
    USD_CNY = auto()
    US_10Y_YIELD = auto()
    """The United States Treasury's 10-year par yield, in percent."""

    US_2Y_YIELD = auto()

    @property
    def in_percent(self) -> bool:
        """Whether its reading is a percentage, whose move is said in percentage points and not as a share of itself."""
        match self:
            case WorldIndicator.US_10Y_YIELD | WorldIndicator.US_2Y_YIELD:
                return True
            case _:
                return False

    @property
    def label(self) -> str:
        """The indicator as the prompt names it to the AI."""
        match self:
            case WorldIndicator.USD_TWD:
                return "USD/TWD exchange rate"
            case WorldIndicator.USD_JPY:
                return "USD/JPY exchange rate"
            case WorldIndicator.EUR_USD:
                return "EUR/USD exchange rate"
            case WorldIndicator.USD_CNY:
                return "USD/CNY exchange rate"
            case WorldIndicator.US_10Y_YIELD:
                return "US 10-year Treasury yield"
            case WorldIndicator.US_2Y_YIELD:
                return "US 2-year Treasury yield"


class TableFormat(StrEnum):
    """How a source serves a table of dated rows."""

    JSON = auto()
    """A JSON list of objects, one per day."""

    CSV = auto()
    """Comma-separated values under a header line, one line per day."""


class AnnualReportSection(StrEnum):
    """
    A part of a shareholders'-meeting annual report the site keeps as text: the parts of its chapter on operations
    that say what the company makes, for whom and with whom. The settings name each part's heading in the report's
    language and what marks it in the text (sources.annual_reports).
    """

    BUSINESS_SCOPE = auto()
    PRODUCT_MIX = auto()
    """The main products with each one's share of revenue."""

    MAJOR_CUSTOMERS = auto()
    """The customers that took a tenth or more of sales in either of the last two years."""

    INDUSTRY_OVERVIEW = auto()
    EMPLOYEES = auto()


class BriefStatus(StrEnum):
    """Where a stock's AI brief of one day stands. One brief exists per stock and Taipei calendar day, for the whole site."""

    WRITING = auto()
    """A request claimed the day's brief and the AI is asked. A claim older than stock_page.brief.claim_minutes was left behind."""

    WRITTEN = auto()
    """The AI's reply passed the reply contract and the day's brief is kept. Nothing follows: the day spends no second call."""

    FAILED = auto()
    """The AI call failed or its reply broke the contract. A viewer may ask again, which claims the day anew."""

    @property
    def next_statuses(self) -> frozenset[BriefStatus]:
        match self:
            case BriefStatus.WRITING:
                return frozenset({BriefStatus.WRITTEN, BriefStatus.FAILED})
            case BriefStatus.FAILED:
                return frozenset({BriefStatus.WRITING})
            case BriefStatus.WRITTEN:
                return frozenset()


class BriefKind(StrEnum):
    """
    Which of the site's AI texts a text is: one of the two about a stock, or the world brief. Its value is the part of
    the AI's reply that must hold a sentence for the text to be kept.
    """

    MOVEMENT = auto()
    """The daily brief: how the held facts of a recent window relate to the stock's move. One per stock and Taipei day."""

    COMPANY = auto()
    """
    The company card: what the company makes and sells, to whom, and its scale. It is written once from the company's
    profile and its annual report and kept: a new one is written only when what it was written from changed.
    """

    WORLD = auto()
    """
    The world brief: what moved in the held world indicators and which held world news may bear on Taiwan's market.
    One per Taipei day, under MarketScope.WORLD in place of a stock.
    """

    @property
    def daily(self) -> bool:
        """
        Whether the text is written anew each Taipei day, whatever it rests on. A text that is not is written once and
        kept until what it rests on changes, and not at all while its prompt is unset.
        """
        match self:
            case BriefKind.MOVEMENT | BriefKind.WORLD:
                return True
            case BriefKind.COMPANY:
                return False


class BriefLanguage(StrEnum):
    """The language the site's AI briefs are written in. Its value is the web app's locale code."""

    TRADITIONAL_CHINESE = "zh-TW"
    ENGLISH = "en"

    @property
    def label(self) -> str:
        """The language as the prompt names it to the AI."""
        match self:
            case BriefLanguage.TRADITIONAL_CHINESE:
                return "Traditional Chinese as written in Taiwan"
            case BriefLanguage.ENGLISH:
                return "English"


class EmbeddingPooling(StrEnum):
    """How a text embedding model's output for a text's tokens becomes the text's one vector, as the model's card states it."""

    CLS = auto()
    """The output of the first token."""

    MEAN = auto()
    """The mean of every token's output."""


class BriefSourceKind(StrEnum):
    """What kind of held item a brief's sentence cites, so the stock page can name it and link to where it shows it."""

    COMPANY = auto()
    """
    What the company is: in a company card, the exchanges' open data of it, its names, market, industry, dates, capital
    and people; in a daily brief, the company card's text, or its listing and its revenue of the latest held months
    while it has no card.
    """

    PRICE = auto()
    """The closes of the brief's window of sessions, from the site's daily history."""

    REVENUE = auto()
    """One held month of revenue."""

    EARNINGS = auto()
    """One held quarter's EPS and margins."""

    RANKING = auto()
    """The stock's standing in the monthly ranking."""

    ANNOUNCEMENT = auto()
    """Material information the company announced."""

    EXCHANGE_NEWS = auto()
    """An item of TWSE's own news."""

    NEWS = auto()
    """A news site's article, by its headline."""

    POST = auto()
    """A stock board's post, by its title."""

    ANNUAL_REPORT = auto()
    """A section of the company's annual report, by its title, with the address of the document site's page that lists the report."""

    PROFILE = auto()
    """The company's main business as it filed it with MOPS, with the address of MOPS's page of the company's basic information."""

    WORLD_NEWS = auto()
    """An item of a world news feed, by its title, with its own address."""

    INDICATOR = auto()
    """A held world indicator's newest reading and its change from the reading before."""

    @property
    def label(self) -> str:
        """The kind as the prompt names it to the AI."""
        return self.value.replace("_", " ")


class ReadingKind(StrEnum):
    """
    One sentence of a stock page's reading of its held figures, which the web app says in the reader's language. A
    reading with a count names how many months, quarters or sessions it holds for.
    """

    REVENUE_ACCELERATING = auto()
    """The latest months' average revenue has been above the longer average for `count` months in a row."""

    REVENUE_SLOWING = auto()
    """The latest months' average revenue has been below the longer average for `count` months in a row."""

    REVENUE_GROWING = auto()
    """Revenue has been above the same month a year before for `count` months in a row."""

    REVENUE_SHRINKING = auto()
    """Revenue has been below the same month a year before for `count` months in a row."""

    REVENUE_HISTORY_SHORT = auto()
    """Only `count` months of revenue are held, too few for the acceleration."""

    NO_REVENUE = auto()
    EPS_UP = auto()
    """The EPS of the year to the quarter's end has been above a year before for `count` quarters in a row."""

    EPS_DOWN = auto()
    """The EPS of the year to the quarter's end has been below a year before for `count` quarters in a row."""

    EPS_HISTORY_SHORT = auto()
    """`count` quarters of EPS are held, the latest with no change from a year before: that quarter is not held, or was a loss."""

    NO_EPS = auto()
    PE_ABOVE_MEDIAN = auto()
    """The latest P/E is above the median of the `count` sessions held."""

    PE_BELOW_MEDIAN = auto()
    """The latest P/E is below the median of the `count` sessions held."""

    PE_AT_MEDIAN = auto()
    NO_PE = auto()
    """The exchange gives no P/E for the latest session, as for a company with losses."""

    VALUATION_HISTORY_SHORT = auto()
    """Only `count` sessions of valuation ratios are held, too few to compare the latest with."""

    NO_VALUATION = auto()


class RankingExclusion(StrEnum):
    """Why the monthly ranking gives a stock no score at a decision session, the first that applies."""

    NO_HISTORY = auto()
    """The held daily history has no bar of it."""

    NOT_A_STOCK = auto()
    """An ETF, which the ranking's universe leaves out."""

    NOT_TRADED = auto()
    """It did not trade at the decision session."""

    PRICE_UNDER_FLOOR = auto()
    """It closed under ranking.min_close."""

    ILLIQUID = auto()
    """Its average traded value over ranking.traded_value_sessions is under ranking.min_traded_value."""

    NO_REVENUE_HISTORY = auto()
    """The revenue of one of the ranking.revenue_long_months months the acceleration reads is not held."""

    SHORT_PRICE_HISTORY = auto()
    """The held history is shorter than the ranking.high_sessions sessions the nearness to the high reads."""


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
    """The simulation key pair, which environments dev and test read."""

    SECRET_KEY_TEST = "SHIOAJI_SECRET_KEY_TEST"


class ExecutionProvider(StrEnum):
    """
    A broker a run may order on, chosen when the run starts. Its properties are the one table of what each broker
    needs; the order gates, the wiring and the pages read them, and nothing else decides by broker.
    """

    MOCK = auto()
    """The user's own mock account, kept in the app's database: the default everywhere, and a follow's only broker."""

    SHIOAJI = auto()
    """SinoPac through the Shioaji API, on the site's own login: its simulation server in dev and test, the real account in prod."""

    @property
    def label(self) -> str:
        match self:
            case ExecutionProvider.MOCK:
                return "the mock account"
            case ExecutionProvider.SHIOAJI:
                return "SinoPac"

    @property
    def real(self) -> bool:
        """
        A broker outside the app, reached on a login: only a user with USE_REAL_BROKER may order on it, only while its
        login is up on the server the environment trades on, and every BUY is held to the trading limits.
        """
        match self:
            case ExecutionProvider.MOCK:
                return False
            case ExecutionProvider.SHIOAJI:
                return True

    @property
    def account_feature(self) -> Feature:
        """The feature reading the broker's account belongs to: the site shows the account only with it."""
        match self:
            case ExecutionProvider.MOCK:
                return Feature.MOCK_ACCOUNT
            case ExecutionProvider.SHIOAJI:
                return Feature.SINOPAC_ACCOUNT

    @property
    def ordering_feature(self) -> Feature:
        """
        The feature ordering on the broker belongs to: the site offers the broker for a run only with it, and a real
        broker's order is refused at the send without it (BrokerAccessRule).
        """
        match self:
            case ExecutionProvider.MOCK:
                return Feature.MOCK_ACCOUNT
            case ExecutionProvider.SHIOAJI:
                return Feature.SINOPAC_ORDERING


class SystemEnvironment(StrEnum):
    """
    Which machine the app runs on, and with it which Shioaji server it trades on. Its properties are the one table of
    what each environment allows; the trading setup check, the broker login and the order gates read them, and
    nothing else decides by environment. A process takes its environment at start: neither the Web editor nor a
    reload changes it.
    """

    DEV = auto()
    """A developer's machine: Shioaji's simulation server, with the *_TEST key pair."""

    TEST = auto()
    """Staging before launch: Shioaji's simulation server, with the *_TEST key pair."""

    PROD = auto()
    """The live service: Shioaji's real account, with the production credentials. The only real money."""

    @property
    def shioaji_credentials(self) -> tuple[ShioajiCredential, ...]:
        """
        The variables a Shioaji login reads here: the API key and the secret key, and in production the CA certificate's
        path, its password and the person id. ShioajiConfig.login reads each by name. The realtime quotes need only the
        key pair; Shioaji as the broker needs them all.
        """
        match self:
            case SystemEnvironment.DEV | SystemEnvironment.TEST:
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
        """
        Shioaji's paper-trading server, or the real account: the login is made on it, and the order gates refuse a
        SinoPac order on a login on any other. Never configured: dev and test are always simulation, prod never.
        """
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

    @property
    def api_docs(self) -> bool:
        """The Web API serves /docs, /redoc and /openapi.json to anyone who reaches it: on a developer's machine only."""
        return self == SystemEnvironment.DEV


class Audience(StrEnum):
    """
    Whom the deployment serves, and with it which data and brokers it may use. Its properties are the one table of
    what each audience allows; the wiring, the trading setup check and the gates of the Web API and the CLI read them,
    and nothing else decides by audience.
    """

    PERSONAL = auto()
    """
    The owner on their own machine: the daily history of the exchanges' own reports of each date, Shioaji's realtime
    quotes on the owner's own login, the news sites, the AI's web search, MOPS, PTT and any broker the environment
    allows. Without that login it has no realtime quote.
    """

    PUBLIC = auto()
    """
    A free public website: only open-licensed data, the TWSE and TPEX OpenAPI as the open-data archive keeps them (Open
    Government Data License v1), and the mock broker. Shioaji's market data comes with the owner's own broker login,
    Yahoo's terms forbid automated collection, cnyes forbids reproduction without consent, MOPS and the exchange's
    document site disallow every robot
    and TWSE's terms forbid the automated download of its site's reports, and nobody may trade in a visitor's account.
    """

    @property
    def open_data_only(self) -> bool:
        """
        Daily history and the index trend come from the open-data archive alone, never from the exchanges' own reports
        of each date on their sites, which give a personal site every session without a login.
        """
        match self:
            case Audience.PERSONAL:
                return False
            case Audience.PUBLIC:
                return True

    @property
    def realtime_quotes(self) -> bool:
        """
        Shioaji's realtime quotes, which price every order: Buzz, Intraday and manual BUY need them. Open data has none.
        Without them Buzz never runs, and PTT, which Buzz and a personal site's stock pages read, is never built. A
        personal site without a Shioaji
        login has none either: every quote is refused, so nothing is ordered.
        """
        return not self.open_data_only

    @property
    def news_articles(self) -> bool:
        """
        The news sites' articles (cnyes, Yahoo Taiwan) and the AI's web search. Without them a stock's articles are the
        material information and the TWSE news naming it that the open-data archive holds of the last
        analysis.material_information_days, and a stock with none of them and no archived financials is decided on its
        technical score alone, without an AI call.
        """
        return not self.open_data_only

    @property
    def mops(self) -> bool:
        """The MOPS income statements, whose EPS the valuation (menus 5 and 6) reads. Without them the valuation is refused."""
        return not self.open_data_only

    @property
    def annual_reports(self) -> bool:
        """
        The companies' annual reports on the exchange's document site (doc.twse.com.tw), which disallows every robot
        as MOPS does. Without them a company card rests on the exchanges' open data alone.
        """
        return not self.open_data_only

    @property
    def world_sources(self) -> frozenset[InformationSource]:
        """
        The world news feeds it may read. A personal site reads every one, as a feed reader does. A public site shows
        what it reads to anyone, so it reads only a feed whose text is free to republish: the Federal Reserve's, a
        United States government work. CNA and the BBC offer their feeds for a reader's own use.
        """
        match self:
            case Audience.PERSONAL:
                return frozenset(source for source in InformationSource if source.is_world)
            case Audience.PUBLIC:
                return frozenset({InformationSource.FEDERAL_RESERVE})

    @property
    def world_indicators(self) -> frozenset[WorldIndicator]:
        """
        The world indicators it may read. A personal site reads every one. A public site shows what it reads to
        anyone, so it reads only the United States Treasury's yields, a government work: the Taiwan Futures Exchange
        offers its open API to connect to and reserves the republication of its data.
        """
        match self:
            case Audience.PERSONAL:
                return frozenset(WorldIndicator)
            case Audience.PUBLIC:
                return frozenset({WorldIndicator.US_10Y_YIELD, WorldIndicator.US_2Y_YIELD})

    @property
    def brokers(self) -> frozenset[ExecutionProvider]:
        """The brokers it may trade on, within those the environment allows."""
        match self:
            case Audience.PERSONAL:
                return frozenset(ExecutionProvider)
            case Audience.PUBLIC:
                return frozenset({ExecutionProvider.MOCK})

    @property
    def order_pricing(self) -> OrderPricing:
        """How its orders are priced: a realtime quote where it has them, else the official close."""
        return OrderPricing.REALTIME_QUOTE if self.realtime_quotes else OrderPricing.OFFICIAL_CLOSE


class Workflow(StrEnum):
    """The user-facing operation a run belongs to. Each run has one run id."""

    FULL_CYCLE = auto()
    BUZZ_SCAN = auto()
    INTRADAY = auto()
    SPECIFIC_STOCKS = auto()
    MANUAL_BUY = auto()
    FOLLOW = auto()
    """
    The user's follow of a finished run's decisions into their mock account, as its own recorded run that names the run
    it followed.
    """

    RANKING_FOLLOW = auto()
    """The user's follow of the monthly ranking's latest decision into their mock account, as its own recorded run."""

    VALUATION = auto()
    """Menus 5 and 6. Read-only: no run record, no order."""

    RESEARCH = auto()
    """The Web stock page's technical evaluation, and the account history. Read-only: no run record, no AI call, no order."""

    @property
    def followable(self) -> bool:
        """
        Its decisions are recorded and never ordered, so a user may follow them into their mock account. Buzz, Intraday,
        the manual BUY and a follow already ordered theirs: following one would order the same decisions twice.
        """
        return self == Workflow.FULL_CYCLE


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


class FinancialStatement(StrEnum):
    """A quarterly financial statement the TWSE and TPEX OpenAPI serve, in one report per industry format."""

    BALANCE_SHEET = auto()
    """The assets, liabilities and equity at the quarter's end."""

    INCOME_STATEMENT = auto()
    """The revenue, costs and income of the year to the quarter's end."""


class IndustryFormat(StrEnum):
    """
    The layout a company files its financial statements in. The OpenAPI serves each format as its own report, with its
    own columns, and names the report after the value: t187ap07_L_ci is the general format's listed balance sheets.
    """

    GENERAL = "ci"
    BANK = "basi"
    SECURITIES = "bd"
    """Securities and futures firms."""

    FINANCIAL_HOLDING = "fh"
    INSURANCE = "ins"
    OTHER = "mim"
    """Companies whose statements fit none of the others."""


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
    A key of config/instructions.yaml: an AI prompt, or a text the site applies beside one, and the setting
    load_settings copies it into. One table for the copy, for refusing any other key of the file, and for placing a
    refused prompt back on its line there.
    """

    SYSTEM_PROMPT = "system_prompt"
    RAG_INJECTION_PROMPT = "rag_injection_prompt"
    ANALYSIS_REPORT_FUNDAMENTAL = "ai_analysis_report_prompt_fundamental"
    ANALYSIS_REPORT_MOMENTUM = "ai_analysis_report_prompt_momentum"
    VALUATION_EXPLANATION = "ai_valuation_explanation_prompt"
    SOCIAL_SENTIMENT = "social_sentiment_prompt"
    STOCK_BRIEF = "stock_brief_prompt"
    STOCK_BRIEF_ADVICE_PHRASES = "stock_brief_advice_phrases"
    STOCK_BRIEF_RISE_QUERY = "stock_brief_rise_query"
    STOCK_BRIEF_FALL_QUERY = "stock_brief_fall_query"
    STOCK_BRIEF_COMPANY_QUERY = "stock_brief_company_query"
    COMPANY_CARD = "company_card_prompt"
    WORLD_BRIEF = "world_brief_prompt"
    WORLD_BRIEF_QUERY = "world_brief_query"

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
            case InstructionKey.STOCK_BRIEF | InstructionKey.COMPANY_CARD | InstructionKey.WORLD_BRIEF:
                return f"prompts.{self.value.removesuffix('_prompt')}"
            case (
                InstructionKey.WORLD_BRIEF_QUERY
                | InstructionKey.STOCK_BRIEF_ADVICE_PHRASES
                | InstructionKey.STOCK_BRIEF_RISE_QUERY
                | InstructionKey.STOCK_BRIEF_FALL_QUERY
                | InstructionKey.STOCK_BRIEF_COMPANY_QUERY
            ):
                return f"prompts.{self.value}"


class SettingsAction(StrEnum):
    SAVE = auto()


class SettingKind(StrEnum):
    """
    The control the administrator's settings form gives a setting. All but the last three are chosen, never typed.
    """

    SWITCH = auto()
    """On or off."""

    CHOICE = auto()
    """One of the setting's options."""

    CHOICES = auto()
    """Any of the setting's options, in order."""

    STEPS = auto()
    """A number picked from the setting's steps, the values that make sense for it."""

    RANGE = auto()
    """A number moved between the setting's minimum and maximum by its step."""

    DATE = auto()
    """A day, picked from a calendar."""

    TIME = auto()
    """A time of day, picked from a clock."""

    TEXT = auto()
    """A text of one line or several, such as an AI prompt. Typed."""

    LINES = auto()
    """A list of texts or numbers, one per line. Typed."""

    STRUCTURE = auto()
    """A map, or a list of maps or lists, taken whole. Typed."""

    @property
    def typed(self) -> bool:
        """The administrator types the value, so the form keeps the setting in its advanced group."""
        match self:
            case SettingKind.TEXT | SettingKind.LINES | SettingKind.STRUCTURE:
                return True
            case _:
                return False


class SettingGroup(StrEnum):
    """What an administrator comes to the settings form to do. Each setting shows under one, in this order."""

    SITE_ACCESS = auto()
    """Who may sign in and register, and how much each user may use."""

    FEATURES = auto()
    """Which parts of the site show, and to whom."""

    RANKING = auto()
    """The monthly ranking and its backtest."""

    DATA_HISTORY = auto()
    """What the site collects and keeps, how often, and how old it may be."""

    AI = auto()
    """The AI models, their search, and the analyses that call them."""

    TRADING_LIMITS = auto()
    """Analysis thresholds, costs, the mock account and the limits of a real broker."""

    ADVANCED = auto()
    """Typed settings and the wiring of data sources: addresses, column names, patterns, prompts and file paths."""


class SettingUnit(StrEnum):
    """What a setting's number counts, so the form words a value as 2%, 15 minutes or NT$100,000."""

    PERCENT = auto()
    """A fraction shown as a percentage: 0.02 is 2%."""

    SECONDS = auto()
    MINUTES = auto()
    HOURS = auto()
    DAYS = auto()
    TWD = auto()
    """New Taiwan dollars."""


class Feature(StrEnum):
    """
    A part of the product the site shows or hides. Its value names its setting under `features` in
    config/appsetting.yaml, which holds its FeatureVisibility. The Web API's routes name the feature they belong to
    (shows() in d_presentation/web/session.py), and the web app's navigation and pages name the same members, so the
    three never disagree about what a feature covers.
    """

    MARKET_OVERVIEW = auto()
    """The home page: the index trend, the most traded stocks and the session's breadth."""

    RANKING = auto()
    """The monthly ranking and its backtest."""

    STOCK_PAGES = auto()
    """A stock's page: its financials and its evaluation by the active strategy."""

    WATCHLIST = auto()
    VALUATION = auto()
    """The P/E valuation, the undervalued scan and their AI explanations."""

    FULL_CYCLE = auto()
    """Starting the after-market full-universe analysis."""

    SPECIFIC_STOCK = auto()
    """Starting the analysis of chosen stocks, and its manual BUY."""

    BUZZ = auto()
    """Starting Social Buzz."""

    INTRADAY = auto()
    """Starting Intraday."""

    STRATEGY_LIBRARY = auto()
    """The technical strategies, and the choice of the active one."""

    STRATEGY_DESIGNER = auto()
    """Writing and changing a technical strategy."""

    STRATEGY_BACKTEST = auto()
    """Replaying the active strategy over a past period."""

    MOCK_ACCOUNT = auto()
    """The mock account, its trades, its reset, and every order placed on it: a follow, Buzz, Intraday, a manual BUY."""

    SINOPAC_ACCOUNT = auto()
    """
    Reading the SinoPac account as the broker reports it: holdings, cash and settlements, profit and loss, fills. It
    never orders, and showing it grants nothing: only a user with USE_REAL_BROKER reads the account, while the login is up.
    """

    SINOPAC_ORDERING = auto()
    """
    Every order placed on the SinoPac account. While it is off, no run starts on SinoPac and no order reaches it,
    whatever the environment and whoever the user is. A run already under way when it is turned off sends no order
    after that: each order asks the switch the site holds at the send (IOrderingSwitch), not the settings the run
    started on. Showing it grants nothing more: USE_REAL_BROKER, the broker's login and the order gates still decide at
    each order.
    """

    HOLDINGS = auto()
    """My holdings: the holdings a user enters by hand, analysed with those of the accounts the site shows the user."""

    WORLD = auto()
    """The world page and the home page's world block: the held world indicators, the day's world brief and the world news."""

    @property
    def run_start(self) -> bool:
        """The feature starts a kind of run. A user who may start none has no runs page."""
        match self:
            case Feature.FULL_CYCLE | Feature.SPECIFIC_STOCK | Feature.BUZZ | Feature.INTRADAY:
                return True
            case _:
                return False


class HoldingSource(StrEnum):
    """Where a holding of the My holdings page comes from. A holding is counted under its one source."""

    BROKERAGE = auto()
    """The SinoPac account, as the broker reports it now."""

    MOCK = auto()
    """The user's mock account."""

    MANUAL = auto()
    """Entered by hand by the user."""

    @property
    def feature(self) -> Feature:
        """The feature the source's holdings belong to: the page reads a source only where the site shows the viewer it."""
        match self:
            case HoldingSource.BROKERAGE:
                return Feature.SINOPAC_ACCOUNT
            case HoldingSource.MOCK:
                return Feature.MOCK_ACCOUNT
            case HoldingSource.MANUAL:
                return Feature.HOLDINGS

    @property
    def permission(self) -> Permission | None:
        """The permission reading the source needs beyond its feature: the real broker's account is the site's own, not a user's."""
        match self:
            case HoldingSource.BROKERAGE:
                return Permission.USE_REAL_BROKER
            case HoldingSource.MOCK | HoldingSource.MANUAL:
                return None


class FeatureVisibility(StrEnum):
    """Who the site shows a feature to. The Web API refuses the feature's routes to everyone else."""

    OFF = auto()
    """Nobody."""

    ADMINISTRATORS = auto()
    """Only a user whose role has SEE_ADMINISTRATOR_FEATURES."""

    EVERYONE = auto()
    """Every signed-in user. A page that needs no sign-in stays open to a visitor too."""

    def shown_to(self, permissions: frozenset[Permission]) -> bool:
        """Whether a viewer with these permissions sees the feature; a visitor has none."""
        match self:
            case FeatureVisibility.OFF:
                return False
            case FeatureVisibility.ADMINISTRATORS:
                return Permission.SEE_ADMINISTRATOR_FEATURES in permissions
            case FeatureVisibility.EVERYONE:
                return True


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
    FEATURE_HIDDEN = auto()
    """The site does not show the route's feature to this viewer (features.* in appsetting.yaml)."""

    REAL_BROKER_REFUSED = auto()
    """A user without USE_REAL_BROKER asked for a run or an account on a real broker."""

    BROKER_UNAVAILABLE = auto()
    """The real broker asked for has no login up on this site now, or the site's audience offers none (public)."""

    REALTIME_QUOTES_UNAVAILABLE = auto()
    """The deployment uses open data only (audience public), which has no realtime quote to order on: Buzz and Intraday."""

    MOPS_UNAVAILABLE = auto()
    """The deployment uses open data only (audience public) and reads no MOPS income statement: the valuation, menus 5 and 6."""

    PASSWORD_REQUIRED = auto()
    PASSWORD_REFUSED = auto()
    GOOGLE_CONFIRMATION_REQUIRED = auto()
    SETTINGS_FILE_REFUSED = auto()
    SETTINGS_FILE_MISSING = auto()
    SETTINGS_CONFLICT = auto()
    SETTINGS_EDIT_REFUSED = auto()
    SETTINGS_REFUSED = auto()
    """The app would not start with the settings: the answer also lists `problems`, each at its file, line and column."""

    TECHNICAL_SETTINGS_CONFLICT = auto()
    AI_MODEL_NOT_OFFERED = auto()
    RUN_IN_PROGRESS = auto()
    TOO_MANY_RUNS = auto()
    NOTHING_TO_FOLLOW = auto()
    """FollowRefusal.NOTHING_TO_FOLLOW: no decision of the run is left to follow."""

    OUTSIDE_FOLLOW_WINDOW = auto()
    """FollowRefusal.OUTSIDE_FOLLOW_WINDOW: the site places no order in the market's phase now."""

    BACKTEST_PERIOD_UNAVAILABLE = auto()
    """The daily history the site holds cannot replay the period asked: `detail` says which days a backtest may cover."""

    RANKING_UNAVAILABLE = auto()
    """The daily history the site holds has no decision session of the monthly ranking yet: `detail` says what it holds."""

    TOO_MANY_BACKTESTS = auto()
    """accounts.max_backtests_per_user of the user's strategy backtests and ranking backtests replay or wait already."""

    AI_ALLOWANCE_SPENT = auto()
    """Today's paid AI calls are spent, the user's (accounts.daily_ai_calls) or every user's together, until midnight Taiwan time."""

    BRIEF_LIMIT_REACHED = auto()
    """stock_page.brief.daily_stocks stocks got a new AI brief today already. Stored briefs stay readable."""

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
    """The settings form of config/appsetting.yaml and config/instructions.yaml: /v1/admin/settings. Checked by requires()."""

    USE_CLI = auto()
    """Sign in to the CLI. Checked by the CLI's sign-in."""

    USE_REAL_BROKER = auto()
    """
    Choose a real broker (ExecutionProvider.real) for a run, and read its account. Checked where dependencies.py builds
    a Pipeline on it, so no other user's Pipeline ever holds it, and again at each order by BrokerAccessRule against the
    user as saved then.
    """

    NOTIFY_RECIPIENTS = auto()
    """This user's run reports go to the installation's LINE recipients. Checked where dependencies.py builds Reporting."""

    UNCAPPED_AI = auto()
    """
    No per-user daily limit on paid AI calls (accounts.daily_ai_calls). The calls still count toward the server's daily
    total, which never refuses them. Checked where dependencies.py builds the user's AI provider.
    """

    SEE_ADMINISTRATOR_FEATURES = auto()
    """Use a feature the site shows to administrators only (FeatureVisibility.ADMINISTRATORS). Checked by shows()."""

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

    GOOGLE_SIGN_IN = auto()
    """Sign-ins with Google one client address started, and its returns from Google. A return that succeeds takes both back."""


class GoogleRefusal(StrEnum):
    """
    Why a sign-in with Google, or a settings confirmation by one, ended without what it was for. The web app shows its
    own words for each; the label is what the server logs.
    """

    NOT_OFFERED = auto()
    FLOW_MISSING = auto()
    """The browser returned without the cookie its start set: it expired, or the start was at another address of the site."""

    STATE_MISMATCH = auto()
    CANCELLED = auto()
    """Google sent the browser back with an error instead of a code, as when the person cancels."""

    PROVIDER_FAILED = auto()
    """Google's token endpoint refused the code, did not answer, or answered no ID token the app can read."""

    TOKEN_REFUSED = auto()
    """The ID token names another issuer, audience or nonce, or expired."""

    EMAIL_UNVERIFIED = auto()
    NOT_ALLOWED = auto()
    """The email is on neither list and registration is closed. No account is created."""

    DEACTIVATED = auto()
    STALE_AUTHENTICATION = auto()
    """A settings confirmation whose Google authentication is older than accounts.google_fresh_authentication_seconds, or undated."""

    NOT_ADMINISTRATOR = auto()
    """
    A settings confirmation started without the session of an active administrator, or by a Google account that is not
    that administrator's.
    """

    @property
    def label(self) -> str:
        return self.value.replace("_", " ")


class UserStatus(StrEnum):
    ACTIVE = auto()
    """May sign in. Every session of the user is valid until it expires."""

    DEACTIVATED = auto()
    """
    May not sign in, and every session ended at the change. A run already running finishes. The user's data stays, and
    reactivation restores access.
    """
