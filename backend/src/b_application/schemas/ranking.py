from dataclasses import dataclass

from a_domain.rules.trading.ranking_backtest import RankingBacktest
from a_domain.types.values import FormulaId


@dataclass(frozen=True)
class FormulaComparison:
    """The ranking page's evidence beside the choice of a formula, as RankingEvidence answers it."""

    active: FormulaId
    """The name of the active formula."""

    evidence: list[tuple[RankingBacktest, RankingBacktest]]
    """Each formula of the settings replayed at its own liquidity floor, then at the comparison's, in the settings' order."""
