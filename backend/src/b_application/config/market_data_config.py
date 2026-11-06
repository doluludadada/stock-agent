from datetime import time
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class MarketHoursConfig(BaseModel):
    """
    The regular TWSE and TPEx trading day on weekdays, in Asia/Taipei time.

    Both exchanges take orders from `opening_auction_start`, match the opening call auction at `continuous_start`,
    trade continuously until `closing_auction_start` and run the closing call auction until `close`. A session's
    daily bar is final in every price source from `settled`.
    """

    opening_auction_start: time = time(8, 30)
    continuous_start: time = time(9, 0)
    closing_auction_start: time = time(13, 25)
    close: time = time(13, 30)
    settled: time = time(15, 0)

    @model_validator(mode="after")
    def validate_order(self) -> Self:
        times = [self.opening_auction_start, self.continuous_start, self.closing_auction_start, self.close, self.settled]

        if any(earlier >= later for earlier, later in zip(times, times[1:], strict=False)):
            raise ValueError(
                "market hours must run opening_auction_start < continuous_start < closing_auction_start < close < settled"
            )

        return self


class MarketDataConfig(BaseModel):
    """How the price and listing adapters pace, batch and cache their requests."""

    model_config = ConfigDict(use_attribute_docstrings=True)

    quote_batch_size: int = Field(default=500, gt=0, le=500)
    """Stocks per Shioaji snapshots request. Shioaji answers at most 500."""

    quote_request_interval_seconds: float = Field(default=0.2, ge=0)
    """
    Least time between two Shioaji quote requests. Shioaji allows 50 market-data queries per 10 seconds, and stops
    answering for a minute after one more.
    """

    quote_timeout_seconds: float = Field(default=10.0, gt=0)

    history_request_interval_seconds: float = Field(default=1.0, ge=0)
    """
    Least time between a daily-history request to Shioaji (a session's daily quotes, an index's one-minute bars) and
    the market-data request before it. Shioaji documents no limit of the daily quotes' own, so they are paced well
    inside the 50 market-data queries per 10 seconds.
    """

    history_backfill_bars: int = Field(default=251, gt=0)
    """
    Sessions of daily history the Web API's timer keeps for every listed stock on a site with a Shioaji login: the
    stock page's one-year chart. A strategy that needs older sessions fetches them when it runs.
    """

    index_minutes_window_days: int = Field(default=30, gt=0, le=30)
    """Calendar days per request of an index's one-minute bars. Shioaji refuses a range of more than 30 days."""

    history_retry_hours: float = Field(default=2, gt=0)
    """
    A question Shioaji answered with nothing new, such as the daily quotes of a session it does not serve yet, or one
    that failed, as every request does while the login is down, is asked again at most this often.
    """

    history_start_slack_days: int = Field(default=14, ge=0)
    """
    An index history that starts more than this many calendar days after the window asked for is fetched further back:
    holidays such as the Lunar New Year closure leave up to about ten days without a session.
    """

    listing_cache_hours: float = Field(default=6, gt=0)
    """How long the TWSE and TPEX listings, with each stock's latest official close, are reused."""

    listing_timeout_seconds: float = Field(default=30.0, gt=0)

    search_result_limit: int = Field(default=12, gt=0, le=50)
    """The most stocks one search of the listing answers with."""

    most_traded_count: int = Field(default=10, gt=0, le=50)
    """How many of the latest session's most traded stocks the market overview lists."""
