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

    model_config = ConfigDict(extra="forbid")

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

    model_config = ConfigDict(extra="forbid")

    quote_batch_size: int = Field(default=50, gt=0)
    """Stocks per TWSE MIS request. MIS answers 100 channels per request and refuses 200."""

    quote_request_interval_seconds: float = Field(default=5.0, ge=0)
    """MIS asks clients to wait its userDelay (5000 ms) between requests; faster polling is reported to get blocked."""

    quote_timeout_seconds: float = Field(default=10.0, gt=0)

    history_batch_size: int = Field(default=50, gt=0)
    """Stocks per Yahoo daily-history download."""

    history_batch_delay_seconds: float = Field(default=1.5, ge=0)
    """Pause after each Yahoo download."""

    history_retry_hours: float = Field(default=2, gt=0)
    """A history behind the last settled session is asked for again at most this often."""

    history_save_chunk_size: int = Field(default=5_000, gt=0)
    """Cached daily bars written per database commit."""

    listing_cache_hours: float = Field(default=6, gt=0)
    """How long the TWSE and TPEX listings, with each stock's latest official close, are reused."""

    listing_timeout_seconds: float = Field(default=30.0, gt=0)
