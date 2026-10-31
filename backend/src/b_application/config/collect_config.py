from datetime import timedelta

from pydantic import BaseModel, Field

from a_domain.rules.collect.freshness import DataFreshnessRule, MissingSessionRule, RealtimeQuoteRule


class FolderConfig(BaseModel):
    news_archive_dir: str = "news_archive"
    buzz_archive_dir: str = "buzz_archive"
    ai_response_dir: str = "ai_responses"


class CollectRulesConfig(BaseModel):
    """Rules for collecting and filtering data."""

    spam_keywords: set[str] = Field(default_factory=set)
    financial_keywords: set[str] = Field(default_factory=set)

    buzz_min_mentions: int = Field(default=20, ge=0)
    buzz_min_engagement: int = Field(default=100, ge=0)
    social_article_limit: int = Field(default=100, ge=1, le=1000)

    ptt_lookback_days: int = Field(default=5, ge=1, le=30)
    ptt_tags: list[str] = Field(default_factory=list)


class QualityFiltersConfig(BaseModel):
    """Minimum text quality requirements."""

    min_chars_stock: int = Field(default=100, ge=0)
    min_chars_news: int = Field(default=200, ge=0)
    min_chars_gossip: int = Field(default=50, ge=0)


class FreshnessConfig(BaseModel):
    """
    How old market data may be before it is blocked.

    Realtime quotes price orders, so their limit is minutes. Daily history feeds technical
    analysis, so its limit is calendar days and must cover weekends and market holidays.
    The official closes that price a P/E valuation follow DailyCloseFreshnessRule instead: it tolerates
    only the exchanges' publication lag, daily_close_max_missed_sessions weekday sessions.
    """

    realtime_max_lag_minutes: int = Field(default=15, gt=0)
    history_max_lag_days: int = Field(default=10, gt=0)
    missing_session_listed_stocks: int = Field(default=10, gt=0)
    """The most stock ids the run error for histories without the last settled session names."""

    daily_close_max_missed_sessions: int = Field(default=1, ge=0)
    """Weekday sessions that may close after an official close's session before that close is stale."""

    def realtime_rule(self) -> DataFreshnessRule:
        return DataFreshnessRule(max_lag=timedelta(minutes=self.realtime_max_lag_minutes))

    def realtime_quote_rule(self) -> RealtimeQuoteRule:
        return RealtimeQuoteRule(freshness=self.realtime_rule())

    def history_rule(self) -> DataFreshnessRule:
        return DataFreshnessRule(max_lag=timedelta(days=self.history_max_lag_days))

    def missing_session_rule(self) -> MissingSessionRule:
        return MissingSessionRule(listed_stock_limit=self.missing_session_listed_stocks)
