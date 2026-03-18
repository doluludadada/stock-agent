from datetime import datetime, timedelta


class DataFreshnessRule:
    """Ensures realtime data is fresh enough for intraday decision making."""

    def __init__(self, max_lag_minutes: int = 15):
        self._max_lag = timedelta(minutes=max_lag_minutes)

    def is_fresh(self, data_timestamp: datetime, current_time: datetime | None = None) -> bool:
        if current_time is None:
            now = datetime.now(data_timestamp.tzinfo) if data_timestamp.tzinfo else datetime.now()
        else:
            now = current_time
            if now.tzinfo is None and data_timestamp.tzinfo is not None:
                now = now.replace(tzinfo=data_timestamp.tzinfo)

        return (now - data_timestamp) <= self._max_lag
