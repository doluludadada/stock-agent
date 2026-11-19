from dataclasses import dataclass

from a_domain.model.system.stats import SystemStats
from a_domain.rules.trading.follow import FollowAccount, FollowSchedule


@dataclass(frozen=True)
class RankingFollowSettings:
    """A user's ranking follow as Pipeline.load_follow_schedule returns it: RankingFollowSchedule's whole answer."""

    account: FollowAccount
    """The user's follow account, whether a ranking follow may order there now, and the accounts the site offers."""

    schedule: FollowSchedule
    """The user's schedule on that account, the times the site offers, and whether it follows the ranking now."""

    follows: list[SystemStats]
    """The user's ranking follows that took a decision, oldest first, each naming its account and the formula it used."""
