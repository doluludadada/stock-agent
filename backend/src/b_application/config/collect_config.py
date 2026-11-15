from datetime import time, timedelta

from pydantic import BaseModel, ConfigDict, Field

from a_domain.rules.ai.stock_brief import BriefContextRule, BriefReplyRule, BriefSearchRule
from a_domain.rules.ai.world_brief import WorldBriefContextRule, WorldBriefDueRule
from a_domain.rules.collect.freshness import DataFreshnessRule, MissingSessionRule, RealtimeQuoteRule
from a_domain.rules.collect.kept_article import KeptArticleRule
from a_domain.rules.fundamentals.stock_analysis import ValuationStandingRule
from a_domain.types.enums import BriefKind, BriefLanguage, EmbeddingPooling, SettingUnit


class FolderConfig(BaseModel):
    news_archive_dir: str = "news_archive"
    buzz_archive_dir: str = "buzz_archive"
    ai_response_dir: str = "ai_responses"
    embedding_model_dir: str = "embedding_models"
    """Where the text embedding model's files are kept once fetched (stock_page.article_store.embedding)."""


class CollectRulesConfig(BaseModel):
    """Rules for collecting and filtering data. Every value comes from the `collect_rules` section of config/appsetting.yaml."""

    spam_keywords: set[str]
    financial_keywords: set[str]

    buzz_min_mentions: int = Field(ge=0, le=10_000)
    buzz_min_engagement: int = Field(ge=0, le=100_000)
    social_article_limit: int = Field(ge=1, le=1000)

    ptt_lookback_days: int = Field(ge=1, le=30)
    ptt_tags: list[str]


class StockBriefConfig(BaseModel):
    """
    The stock page's AI brief: what the company is and how the held facts of a recent window relate to the stock's move.
    One is written per stock and Taipei calendar day for the whole site, when a signed-in viewer asks for it.
    """

    model_config = ConfigDict(use_attribute_docstrings=True)

    daily_stocks: int = Field(default=30, ge=1, le=1000, json_schema_extra={"steps": [5, 10, 20, 30, 50, 100, 200, 500, 1000]})
    """How many stocks may get a new brief per Taiwan calendar day, for all users together. Stored briefs stay readable past it."""

    language: BriefLanguage = BriefLanguage.TRADITIONAL_CHINESE
    """The language every brief is written in. A viewer who reads the site in another language sees it as written."""

    window_sessions: int = Field(default=20, ge=5, le=120, json_schema_extra={"steps": [5, 10, 20, 40, 60, 120]})
    """The latest sessions whose price move a brief describes, and from whose first day on it reads announcements and news."""

    claim_minutes: int = Field(default=5, ge=1, le=120, json_schema_extra={"operator_only": True})
    """A brief still being written this long after a request claimed it was left behind by a stopped server, and may be asked again."""

    revenue_months: int = Field(default=3, ge=1, le=24, json_schema_extra={"operator_only": True})
    quarters: int = Field(default=2, ge=1, le=12, json_schema_extra={"operator_only": True})
    articles: int = Field(default=12, ge=1, le=50, json_schema_extra={"operator_only": True})
    """The most held months of revenue, quarters with an EPS, and announcements, news items and posts a brief's prompt holds."""

    article_text_length: int = Field(default=200, ge=0, le=2000, json_schema_extra={"operator_only": True})
    """The characters of an announcement's or an exchange news item's own text the prompt holds after its title."""

    largest_moves: int = Field(default=3, ge=1, le=10, json_schema_extra={"operator_only": True})
    """How many of the window's largest daily moves the prompt names, so that a dated fact can be set beside one."""

    sentences: int = Field(default=4, ge=1, le=10, json_schema_extra={"operator_only": True})
    sentence_length: int = Field(default=400, ge=50, le=2000, json_schema_extra={"operator_only": True})
    """The most sentences each of a brief's two parts keeps, and the characters a sentence is cut at."""

    link_pattern: str = Field(default=r"(?i)\(?(?:[a-z][a-z0-9+.-]*://|www\.)\S*", json_schema_extra={"operator_only": True})
    """What is cut out of a sentence the AI wrote as a link (a regular expression): a brief shows only the held items' addresses."""

    lead_days: int = Field(default=30, ge=1, le=365, json_schema_extra={"operator_only": True})
    lead_articles: int = Field(default=3, ge=0, le=20, json_schema_extra={"operator_only": True})
    """The days before the window a brief also searches, and the most kept articles of them its prompt holds."""

    company_days: int = Field(default=730, ge=1, le=3650, json_schema_extra={"operator_only": True})
    company_articles: int = Field(default=4, ge=0, le=20, json_schema_extra={"operator_only": True})
    """The days back a brief searches for what the company makes and sells, and the most kept articles of them its prompt holds."""

    def context_rule(self) -> BriefContextRule:
        return BriefContextRule(
            window_sessions=self.window_sessions,
            revenue_months=self.revenue_months,
            quarters=self.quarters,
            articles=self.articles,
            article_text_length=self.article_text_length,
            largest_moves=self.largest_moves,
        )

    def search_rule(self, rise_query: str, fall_query: str, company_query: str) -> BriefSearchRule:
        """What a brief searches the kept articles for; the queries are prompts.stock_brief_*_query."""
        return BriefSearchRule(
            window_sessions=self.window_sessions,
            rise_query=rise_query,
            fall_query=fall_query,
            company_query=company_query,
            articles=self.articles,
            lead_days=self.lead_days,
            lead_articles=self.lead_articles,
            company_days=self.company_days,
            company_articles=self.company_articles,
        )

    def reply_rule(self, advice_phrases: frozenset[str]) -> BriefReplyRule:
        """The reply contract; `advice_phrases` are those of prompts.stock_brief_advice_phrases."""
        return BriefReplyRule(
            kind=BriefKind.MOVEMENT,
            sentences=self.sentences,
            sentence_length=self.sentence_length,
            link_pattern=self.link_pattern,
            advice_phrases=advice_phrases,
        )


class CompanyCardConfig(BaseModel):
    """
    The stock page's company card: what the company makes and sells, to whom, and its revenue structure and scale, in
    the AI's wording of the company's profile and its annual report's sections, each sentence citing its source. It is
    written once and kept: a new one is written only when what it rests on, its prompt or its language changed. Its
    language is the brief's (stock_page.brief.language), and its prompt is company_card_prompt in
    config/instructions.yaml; without the prompt no card is written.
    """

    model_config = ConfigDict(use_attribute_docstrings=True)

    daily_stocks: int = Field(default=200, ge=1, le=5000, json_schema_extra={"operator_only": True})
    """How many companies may get a new card per Taiwan calendar day at viewers' requests. The site's own writing takes none."""

    sentences: int = Field(default=5, ge=1, le=10, json_schema_extra={"operator_only": True})
    sentence_length: int = Field(default=400, ge=50, le=2000, json_schema_extra={"operator_only": True})
    """The most sentences a card keeps, and the characters a sentence is cut at."""

    section_length: int = Field(default=2500, ge=200, le=20_000, json_schema_extra={"operator_only": True})
    """The characters of each kept annual-report section the card's prompt holds."""

    def reply_rule(self, advice_phrases: frozenset[str], link_pattern: str) -> BriefReplyRule:
        """The reply contract; the phrases and the link pattern are the brief's."""
        return BriefReplyRule(
            kind=BriefKind.COMPANY,
            sentences=self.sentences,
            sentence_length=self.sentence_length,
            link_pattern=link_pattern,
            advice_phrases=advice_phrases,
        )


class SystemWritingConfig(BaseModel):
    """
    The site's own writing: once a session's daily data is held, the Web API's timer makes sure each stock of the
    monthly ranking's top (the active formula's `top`) has its profile, its main business, its annual report's sections, its company
    card and the day's brief, on the AI model ai.system_model. Its calls are counted apart from every user's allowance,
    and its briefs and cards take none of the stocks viewers' requests may claim a day.
    """

    model_config = ConfigDict(use_attribute_docstrings=True)

    daily_ai_calls: int = Field(
        default=0,
        ge=0,
        le=10_000,
        json_schema_extra={"operator_only": True, "without": "the site writes no company card and no brief by itself"},
    )
    """
    The paid AI calls the site's own writing may make per Taiwan calendar day: a brief is one, and a card one more when
    it is written. Past it the round stops and goes on the next day. 0, and a file that does not set it, turn the
    site's own writing off: `without` says so at the start (settings_notices).
    """

    users_stocks: bool = Field(default=False, json_schema_extra={"operator_only": True})
    """Whether a round also writes for the stocks users hold or watch, after the ranking's, within the same budget."""

    @property
    def enabled(self) -> bool:
        """Whether the site writes by itself at all."""
        return self.daily_ai_calls > 0


class EmbeddingConfig(BaseModel):
    """
    The text embedding model the article store's vectors come from. It runs on the server itself with ONNX Runtime, so
    no article leaves the server and no call is paid for. Its files are fetched once from the Hugging Face repository
    into folder.embedding_model_dir, at the pinned revision. Another model, revision or file starts a collection of its
    own, which fills again from the kept articles.
    """

    model_config = ConfigDict(use_attribute_docstrings=True)

    repository: str = "Xenova/bge-small-zh-v1.5"
    revision: str = "75c43b069aac4d136ba6bc1122f995fedcfd2781"
    """The repository's commit the files are read at, so the model never changes under the vectors already kept."""

    model_file: str = "onnx/model_quantized.onnx"
    tokenizer_file: str = "tokenizer.json"
    pooling: EmbeddingPooling = EmbeddingPooling.CLS
    max_tokens: int = Field(default=512, ge=16, le=8192)
    """The most tokens of a text the model reads: its own limit."""

    batch_size: int = Field(default=1, ge=1, le=64)
    threads: int = Field(default=2, ge=1, le=64)
    """
    The texts embedded in one run of the model and the CPU threads a run uses: both bound what embedding takes from the
    server. On a CPU one text a run is as fast as four and needs a third of the memory, which grows with the batch.
    """

    @property
    def identity(self) -> str:
        """What the vectors depend on: vectors of another model, revision, file or pooling cannot be compared with these."""
        return f"{self.repository}@{self.revision}/{self.model_file}/{self.pooling.value}/{self.max_tokens}"


class ArticleStoreConfig(BaseModel):
    """
    The article store: what the site read about each stock, kept so that it accumulates, with a vector per article that
    finds it by meaning. Articles enter it when a stock page asks for the stock's news and when the Web API's timer
    keeps the stocks that matter current.
    """

    model_config = ConfigDict(use_attribute_docstrings=True)

    retention_days: int = Field(
        default=730, ge=30, le=3650, json_schema_extra={"steps": [90, 180, 365, 730, 1095, 1825, 3650], "unit": SettingUnit.DAYS}
    )
    """An article published longer ago than this is dropped from the store."""

    max_per_stock: int = Field(default=300, ge=10, le=5000, json_schema_extra={"steps": [50, 100, 200, 300, 500, 1000, 2000, 5000]})
    """The most articles the store keeps of one stock, the newest first."""

    shown: int = Field(default=50, ge=1, le=500, json_schema_extra={"operator_only": True})
    """The most kept articles a stock page lists, the newest first."""

    text_length: int = Field(default=4000, ge=0, le=100_000, json_schema_extra={"operator_only": True})
    """The characters of an article's text the store keeps."""

    embedded_length: int = Field(default=300, ge=0, le=8000, json_schema_extra={"operator_only": True})
    """The characters of an article's kept text its vector reads after its title. Embedding time grows with them."""

    refresh_stocks: int = Field(default=200, ge=0, le=5000, json_schema_extra={"operator_only": True})
    """
    The most stocks whose news the Web API's timer fetches each time, of the stocks users hold or watch. 0 fetches
    none, and stock pages alone fill the store.
    """

    refresh_pause_seconds: float = Field(default=2, ge=0, le=600, json_schema_extra={"operator_only": True})
    """The least time between two stocks' fetches from the news sites and the board, whoever asks: a page or the timer."""

    embedding: EmbeddingConfig = Field(default_factory=EmbeddingConfig, json_schema_extra={"operator_only": True})

    def retention(self) -> timedelta:
        return timedelta(days=self.retention_days)

    def kept_rule(self, news_text: bool) -> KeptArticleRule:
        """How an article is kept; `news_text` is Audience.news_articles of the site."""
        return KeptArticleRule(news_text=news_text, text_length=self.text_length)


class StockPageConfig(BaseModel):
    """
    The stock page's financial analysis and its related news. The analysis reads held data only; the news of a site
    that may read the news sites and the board is fetched when a page asks and then held.
    """

    model_config = ConfigDict(use_attribute_docstrings=True)

    news_freshness_minutes: int = Field(
        default=30, ge=1, le=1440, json_schema_extra={"steps": [5, 15, 30, 60, 180, 720, 1440], "unit": SettingUnit.MINUTES}
    )
    """How long a stock's fetched news and posts are served again before the news sites and the board are asked anew."""

    news_held_stocks: int = Field(default=300, ge=1, le=5000, json_schema_extra={"steps": [50, 100, 300, 500, 1000, 2000, 5000]})
    """The stocks whose fetched news and posts stay in memory, the most recently asked first."""

    valuation_min_sessions: int = Field(default=60, ge=2, le=2500, json_schema_extra={"steps": [20, 60, 120, 250, 500, 1250]})
    """The sessions of a valuation ratio the page needs before it compares the latest with their median."""

    eps_quarters: int = Field(default=12, ge=1, le=40, json_schema_extra={"steps": [4, 8, 12, 16, 20, 40]})
    """How many of the latest quarters the page reads the EPS of from the MOPS pages a personal site holds."""

    brief: StockBriefConfig = Field(default_factory=StockBriefConfig)
    card: CompanyCardConfig = Field(default_factory=CompanyCardConfig)
    system_writing: SystemWritingConfig = Field(default_factory=SystemWritingConfig)
    article_store: ArticleStoreConfig = Field(default_factory=ArticleStoreConfig)

    def freshness(self) -> timedelta:
        return timedelta(minutes=self.news_freshness_minutes)

    def valuation_rule(self) -> ValuationStandingRule:
        return ValuationStandingRule(min_sessions=self.valuation_min_sessions)


class WorldBriefConfig(BaseModel):
    """
    The day's world brief: what moved in the held world indicators and which held world news may bear on Taiwan's
    market, written once per Taipei day by the site's own writing, on its AI model and its budget
    (stock_page.system_writing). Its language is the stock brief's (stock_page.brief.language), and its prompt is
    world_brief_prompt in config/instructions.yaml.
    """

    model_config = ConfigDict(use_attribute_docstrings=True)

    write_at: time = time(7, 30)
    """
    The Taipei time from which the day's brief is written, at the world timer's next round: after the United States
    session's close and its yields, before the Taiwan open.
    """

    window_hours: int = Field(default=24, ge=6, le=72, json_schema_extra={"steps": [12, 24, 36, 48, 72], "unit": SettingUnit.HOURS})
    """The hours of world news before its writing a brief reads."""

    articles: int = Field(default=60, ge=1, le=300, json_schema_extra={"operator_only": True})
    """The most world news items a brief's prompt holds: those its search finds closest to world_brief_query, newest first."""

    article_text_length: int = Field(default=240, ge=0, le=2000, json_schema_extra={"operator_only": True})
    """The characters of a feed's own summary the prompt holds after an item's title."""

    indicator_days: int = Field(default=5, ge=1, le=30, json_schema_extra={"operator_only": True})
    """An indicator whose newest held reading is older than this many days is left out of a brief."""

    sentences: int = Field(default=8, ge=1, le=20, json_schema_extra={"operator_only": True})
    sentence_length: int = Field(default=400, ge=50, le=2000, json_schema_extra={"operator_only": True})
    """The most sentences a brief keeps, and the characters a sentence is cut at."""

    retry_minutes: int = Field(default=120, ge=5, le=1440, json_schema_extra={"operator_only": True})
    """How long after a failed brief was asked for the day's brief is asked for again, so a failure spends few AI calls."""

    shown_days: int = Field(default=14, ge=1, le=90, json_schema_extra={"operator_only": True})
    """The most past days' briefs the world page offers."""

    def context_rule(self) -> WorldBriefContextRule:
        return WorldBriefContextRule(
            window_hours=self.window_hours,
            articles=self.articles,
            article_text_length=self.article_text_length,
            indicator_days=self.indicator_days,
        )

    def due_rule(self, on: bool, claim_minutes: int) -> WorldBriefDueRule:
        """When the day's brief is asked for; `on` is whether the site writes one at all, `claim_minutes` the stock brief's."""
        return WorldBriefDueRule(
            on=on, write_at=self.write_at, retry=timedelta(minutes=self.retry_minutes), claim_time=timedelta(minutes=claim_minutes)
        )

    def reply_rule(self, advice_phrases: frozenset[str], link_pattern: str) -> BriefReplyRule:
        """The reply contract; the phrases and the link pattern are the stock brief's."""
        return BriefReplyRule(
            kind=BriefKind.WORLD,
            sentences=self.sentences,
            sentence_length=self.sentence_length,
            link_pattern=link_pattern,
            advice_phrases=advice_phrases,
        )


class WorldConfig(BaseModel):
    """
    The world outside Taiwan's exchanges: the world news feeds' items, kept in the article store with a vector each,
    the world indicators' daily readings, and the day's world brief. The Web API's world timer reads the feeds named
    under sources.world every api.world_interval_minutes; a file that names none reads nothing.
    """

    model_config = ConfigDict(use_attribute_docstrings=True)

    retention_days: int = Field(default=14, ge=1, le=365, json_schema_extra={"steps": [7, 14, 30, 60, 90], "unit": SettingUnit.DAYS})
    """A world news item published longer ago than this is dropped. The briefs keep the items they cite."""

    max_items: int = Field(default=3000, ge=100, le=50_000, json_schema_extra={"operator_only": True})
    """The most world news items kept, the newest first."""

    shown: int = Field(default=200, ge=1, le=1000, json_schema_extra={"operator_only": True})
    """The most kept items the world page lists, the newest first."""

    summary_length: int = Field(default=400, ge=0, le=4000, json_schema_extra={"operator_only": True})
    """The characters of a feed's own summary of an item that are kept."""

    brief: WorldBriefConfig = Field(default_factory=WorldBriefConfig)

    def retention(self) -> timedelta:
        return timedelta(days=self.retention_days)


class QualityFiltersConfig(BaseModel):
    """Minimum text quality requirements."""

    min_chars_stock: int = Field(default=100, ge=0, le=10_000, json_schema_extra={"steps": [0, 50, 100, 200, 500]})
    min_chars_news: int = Field(default=200, ge=0, le=10_000, json_schema_extra={"steps": [0, 50, 100, 200, 500]})
    min_chars_gossip: int = Field(default=50, ge=0, le=10_000, json_schema_extra={"steps": [0, 50, 100, 200, 500]})


class FreshnessConfig(BaseModel):
    """
    How old market data may be before it is blocked.

    Realtime quotes price orders, so their limit is minutes. Daily history feeds technical
    analysis, so its limit is calendar days and must cover weekends and market holidays.
    The official closes that price a P/E valuation follow DailyCloseFreshnessRule instead: it tolerates
    only the exchanges' publication lag, daily_close_max_missed_sessions weekday sessions.
    """

    model_config = ConfigDict(use_attribute_docstrings=True)

    realtime_max_lag_minutes: int = Field(
        default=15, gt=0, json_schema_extra={"steps": [1, 5, 10, 15, 30], "unit": SettingUnit.MINUTES}
    )
    history_max_lag_days: int = Field(default=10, gt=0, json_schema_extra={"steps": [5, 7, 10, 14], "unit": SettingUnit.DAYS})
    missing_session_listed_stocks: int = Field(default=10, gt=0, json_schema_extra={"steps": [5, 10, 20, 50]})
    """The most stock ids the run error for histories without the last settled session names."""

    daily_close_max_missed_sessions: int = Field(default=1, ge=0, json_schema_extra={"steps": [0, 1, 2, 3]})
    """Weekday sessions that may close after an official close's session before that close is stale."""

    def realtime_rule(self) -> DataFreshnessRule:
        return DataFreshnessRule(max_lag=timedelta(minutes=self.realtime_max_lag_minutes))

    def realtime_quote_rule(self) -> RealtimeQuoteRule:
        return RealtimeQuoteRule(freshness=self.realtime_rule())

    def history_rule(self) -> DataFreshnessRule:
        return DataFreshnessRule(max_lag=timedelta(days=self.history_max_lag_days))

    def missing_session_rule(self) -> MissingSessionRule:
        return MissingSessionRule(listed_stock_limit=self.missing_session_listed_stocks)
