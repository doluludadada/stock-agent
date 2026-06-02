from dataclasses import dataclass
from datetime import datetime, timedelta


@dataclass(frozen=True)
class DataFreshnessRule:
    """
    Data Freshness Evaluation Rule.

    Ensures that the ingested candlestick (OHLCV) timestamps align with the
    configured tolerance threshold to prevent stale data execution.
    """

    max_lag_minutes: int = 15
    """
    # max_lag_minutes (int): Maximum tolerated age of incoming data before flagging it as stale.
    """

    @property
    def max_lag(self) -> timedelta:
        """Converts the integer configuration into a comparable timedelta."""
        return timedelta(minutes=self.max_lag_minutes)

    def is_fresh(self, data_timestamp: datetime, current_time: datetime | None = None) -> bool:
        """
        Compares the data feed timestamp against current system time.

        Args:
            data_timestamp (datetime): The timestamp of the latest price quote.
            current_time (datetime | None): Optional mock current time (used in tests).

        Returns:
            bool: True if lag is within acceptable limits, False if stale.
        """
        if current_time is None:
            # Match timezone-awareness dynamically to prevent TypeError during comparison
            now = datetime.now(data_timestamp.tzinfo) if data_timestamp.tzinfo else datetime.now()
        else:
            now = current_time
            if now.tzinfo is None and data_timestamp.tzinfo is not None:
                now = now.replace(tzinfo=data_timestamp.tzinfo)

        return (now - data_timestamp) <= self.max_lag
