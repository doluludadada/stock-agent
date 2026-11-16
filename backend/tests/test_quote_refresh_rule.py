"""QuoteRefreshRule: when the quote board asks its source, and what a page is told about asking again."""

from datetime import datetime, timedelta

import pytest
from support.harness import MARKET_OPEN

from a_domain.rules.market.quote_refresh import QuoteRefresh, QuoteRefreshRule
from a_domain.types.enums import TradingPhase

RULE = QuoteRefreshRule(refresh_seconds=10, recheck_seconds=300)
CHANGING = QuoteRefresh(changing=True, seconds=10)
STOPPED = QuoteRefresh(changing=False, seconds=300)
TODAY = MARKET_OPEN.date()
CLOSE = MARKET_OPEN.replace(hour=13, minute=30)


@pytest.mark.parametrize("phase", [phase for phase in TradingPhase if phase is not TradingPhase.CLOSED])
def test_while_a_session_trades_the_quotes_change_whatever_was_read(phase: TradingPhase) -> None:
    assert RULE.apply(phase, TODAY, TODAY - timedelta(days=1), CLOSE, None) == CHANGING
    assert RULE.apply(phase, TODAY, TODAY - timedelta(days=1), CLOSE, CLOSE - timedelta(hours=1)) == CHANGING


@pytest.mark.parametrize("read_at", [None, CLOSE - timedelta(seconds=1)], ids=["never read", "read before the close"])
def test_after_todays_close_the_quotes_change_until_the_source_answered_a_request_made_after_it(read_at: datetime | None) -> None:
    assert RULE.apply(TradingPhase.CLOSED, TODAY, TODAY, CLOSE, read_at) == CHANGING


@pytest.mark.parametrize("read_at", [CLOSE, CLOSE + timedelta(seconds=20)], ids=["read at the close", "read after the close"])
def test_once_the_sessions_last_quotes_are_read_nothing_changes_and_a_page_looks_at_the_longer_interval(read_at: datetime) -> None:
    assert RULE.apply(TradingPhase.CLOSED, TODAY, TODAY, CLOSE, read_at) == STOPPED


@pytest.mark.parametrize("read_at", [None, CLOSE - timedelta(days=1)], ids=["never read", "read the session before"])
def test_before_the_open_and_on_a_day_without_a_session_nothing_changes(read_at: datetime | None) -> None:
    assert RULE.apply(TradingPhase.CLOSED, TODAY, TODAY - timedelta(days=1), CLOSE, read_at) == STOPPED
