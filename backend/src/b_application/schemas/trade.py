from dataclasses import dataclass

from a_domain.model.market.stock import Stock
from a_domain.model.system.stats import SystemStats
from a_domain.model.trading.account import BrokerageStatement
from a_domain.rules.system.settings_change import ServerSwitchRefusal
from a_domain.rules.trading.follow import FollowAccount, FollowReturn, FollowSchedule, RankingHoldings
from a_domain.rules.watchlist.membership import WatchlistAddition
from a_domain.types.enums import FollowRefusal


@dataclass(frozen=True)
class RankingFollowSettings:
    """A user's ranking follow as RankingFollowSchedule answers it and Pipeline.load_follow_schedule returns it."""

    account: FollowAccount
    """The user's follow account, whether a ranking follow may order there now, and the accounts the site offers."""

    schedule: FollowSchedule
    """The user's schedule on that account, the times the site offers, and whether it follows the ranking now."""

    follows: list[SystemStats]
    """The user's ranking follows that took a decision, oldest first, each naming its account and the formula it used."""


@dataclass(frozen=True)
class RankingFollow:
    """The ranking page's follow block, and the check before a ranking follow starts, as Pipeline.load_ranking_follow returns it."""

    settings: RankingFollowSettings
    """RankingFollowSchedule: the user's follow account, their schedule and their ranking follows that took a decision."""

    holdings: RankingHoldings
    """RankingFollowCandidates: which of the ranking's stocks the follow account holds and lacks, and the holdings it left."""

    refusal: FollowRefusal | None
    """RankingFollowCandidates: why a follow may not start now."""

    performance: FollowReturn | None
    """
    RankingFollowReturn: what the mock account made since it first followed the ranking, against the ranking's
    benchmark, while it is the follow account the site offers (FollowAccount.measured); None otherwise.
    """


@dataclass(frozen=True)
class BrokerageAccount:
    """The SinoPac account page, as BrokerageStatementReader answers it for Pipeline.load_brokerage_statement."""

    statement: BrokerageStatement | None
    """The real broker's account as it reports it now; None while the site has no real broker for the user or its login is down."""

    switch_refusal: ServerSwitchRefusal | None
    """Why the site's login could not switch to the other server; None while it could."""


@dataclass(frozen=True)
class ManualWatch:
    """The MANUAL watchlist's addition, as Pipeline.watch_manually returns it."""

    stocks: list[Stock]
    """The listed stocks found of those asked for."""

    addition: WatchlistAddition | None
    """WatchStocks: what joined the watchlist; None, and nothing added, when the listing lacks one of the ids."""
