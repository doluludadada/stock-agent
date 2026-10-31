from dataclasses import dataclass

from a_domain.model.trading.account_snapshot import AccountSnapshot
from a_domain.model.trading.account_valuation import AccountValuation
from a_domain.model.trading.equity_point import EquityPoint


@dataclass(frozen=True)
class AccountHistoryReport:
    current: AccountValuation
    """The account now, each position marked at its latest quote (realtime, else the last daily close)."""

    equity_curve: list[EquityPoint]

    as_of: tuple[AccountSnapshot, AccountValuation] | None
    """The account at the end of the requested day, or None when no fill happened on or before it."""

    live_stock_ids: frozenset[str]
    """The held stocks `current` marks at a realtime quote. Any other position is at its last daily close or unpriced."""
