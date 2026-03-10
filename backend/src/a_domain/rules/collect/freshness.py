from datetime import datetime, timedelta


class DataFreshnessRule:
    """Ensures realtime data is fresh enough for intraday decision making."""

    def __init__(self, max_lag_minutes: int = 15):
        self._max_lag = timedelta(minutes=max_lag_minutes)

    def is_fresh(self, data_timestamp: datetime, current_time: datetime | None = None) -> bool:
        now = current_time or datetime.now()
        return (now - data_timestamp) <= self._max_lag
