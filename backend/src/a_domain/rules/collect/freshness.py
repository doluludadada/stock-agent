# TODO: Not wired yet — planned for data freshness validation
# src/a_domain/rules/collect/freshness.py
from datetime import datetime, timedelta


class DataFreshnessRule:
    """
    Rule: Ensures the data is fresh enough for intraday decision making.
    """

    def __init__(self, max_lag_minutes: int = 15):
        self._max_lag = timedelta(minutes=max_lag_minutes)

    def is_fresh(self, data_timestamp: datetime, current_time: datetime) -> bool:
        return (current_time - data_timestamp) <= self._max_lag


