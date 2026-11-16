import math
from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from typing import Annotated

import numpy as np
from pydantic import Field, FiniteFloat, NonNegativeFloat, PositiveInt
from pydantic.dataclasses import dataclass

from a_domain.model.market.ohlcv import Ohlcv
from a_domain.model.trading.account import Position
from a_domain.rules.fundamentals.stock_analysis import RevenueMonth, RevenueTrend
from a_domain.rules.technical.matrix import DailyBarMatrix
from a_domain.rules.trading.account_value import PositionValueRule
from a_domain.rules.trading.ranking_standing import RankingStanding
from a_domain.types.enums import HoldingSource
from a_domain.types.values import Fraction


@dataclass(frozen=True)
class LastCloseRule:
    """A stock's last close in the held daily history and its session, or None where the history has no bar of it."""

    def apply(self, bars: DailyBarMatrix, stock_id: str) -> tuple[float, date] | None:
        if stock_id not in bars.stock_ids:
            return None

        closes = bars.close[bars.stock_ids.index(stock_id)]
        traded = np.flatnonzero(~np.isnan(closes))

        if not traded.size:
            return None

        return float(closes[traded[-1]]), bars.sessions[traded[-1]]


@dataclass(frozen=True, kw_only=True)
class AnalysedHolding:
    """
    One holding of the My holdings page: what is held, where it comes from, and what the site's held data says of its
    stock. It is data to read, never a recommendation: the score ranks two measured factors and forecasts nothing.
    """

    source: HoldingSource
    position: Position
    """
    Marked at the stock's last close the site holds, or at today's quote where that is newer, net of the SELL fee and
    tax; without a mark where the site holds neither.
    """

    stock_name: str | None
    weight: Fraction
    """Its market value over the portfolio's."""

    standing: RankingStanding | None
    """Where the stock stands in the monthly ranking, or why the ranking leaves it out."""

    revenue: RevenueMonth | None
    """The stock's latest held month of revenue with the ranking's acceleration. None for a stock with no revenue held."""

    accelerating_months: int | None
    """The latest months in a row with an acceleration above 1, negative for below 1 (RevenueTrend.accelerating_months)."""

    @property
    def score(self) -> float | None:
        return None if self.standing is None else self.standing.score


@dataclass(frozen=True, kw_only=True)
class PortfolioAnalysis:
    """
    The holdings read together, each counted once under its source: what they are worth at the last closes held, or
    at today's quotes where those are newer, how concentrated they are, how much of their value the monthly ranking
    holds, and their value-weighted score.
    """

    sources: list[HoldingSource]
    """The sources read, in order. One asked for and absent here could not be read now."""

    holdings: list[AnalysedHolding]
    """Largest market value first."""

    live_stock_ids: list[str]
    """The held stocks valued at today's realtime quote, in order. Every other holding is at its last close, or unpriced."""

    market_value: NonNegativeFloat
    cost: NonNegativeFloat
    unrealized_pnl: FiniteFloat
    """Net of the SELL fee and tax, over the holdings that have a last close."""

    concentration_positions: PositiveInt
    concentration: Fraction
    """The share of the value in the `concentration_positions` largest stocks, a stock held under two sources counted as one."""

    top_share: Fraction
    """The share of the value in stocks the monthly ranking holds now."""

    scored_share: Fraction
    """The share of the value in holdings that have a score. The rest is unscored: ETFs and stocks the ranking leaves out."""

    weighted_score: Annotated[float, Field(ge=0, le=100)] | None
    """The scores weighted by market value over the scored holdings alone. None when no holding has a score."""

    lowest: AnalysedHolding | None
    highest: AnalysedHolding | None
    """The scored holdings with the lowest and the highest score, the largest of equal scores. None when no holding has a score."""

    @property
    def unrealized_return(self) -> float | None:
        """The unrealized PnL over the cost of the holdings it counts, those that have a last close. None when none has."""
        cost = math.fsum(holding.position.cost_basis for holding in self.holdings if holding.position.unrealized_return is not None)
        return self.unrealized_pnl / cost if cost else None


def portfolio_analysis(
    sources: list[HoldingSource], holdings: list[AnalysedHolding], live: list[str], total: float, concentration_positions: PositiveInt
) -> PortfolioAnalysis:
    by_stock: defaultdict[str, float] = defaultdict(float)

    for holding in holdings:
        by_stock[holding.position.stock_id] += holding.weight

    largest = sorted(by_stock.values(), reverse=True)[:concentration_positions]

    scored = [(holding, holding.score) for holding in holdings if holding.score is not None]
    scored_share = math.fsum(holding.weight for holding, _ in scored)
    weighted = math.fsum(holding.weight * score for holding, score in scored)

    return PortfolioAnalysis(
        sources=sources,
        holdings=holdings,
        live_stock_ids=live,
        market_value=total,
        cost=math.fsum(holding.position.cost_basis for holding in holdings),
        unrealized_pnl=math.fsum(holding.position.unrealized_pnl for holding in holdings),
        concentration_positions=concentration_positions,
        concentration=min(1.0, math.fsum(largest)),
        top_share=min(1.0, math.fsum(holding.weight for holding in holdings if holding.standing and holding.standing.in_top)),
        scored_share=min(1.0, scored_share),
        weighted_score=min(100.0, weighted / scored_share) if scored_share else None,
        lowest=min(scored, key=lambda pair: pair[1])[0] if scored else None,
        highest=max(scored, key=lambda pair: pair[1])[0] if scored else None,
    )


def quoted_after(closes: Mapping[str, tuple[float, datetime]], quotes: Mapping[str, Ohlcv]) -> dict[str, tuple[float, datetime]]:
    """The price and time of each quote traded after its stock's last close held, or of a stock with no close held."""
    return {
        stock_id: (quote.close, quote.ts)
        for stock_id, quote in quotes.items()
        if stock_id not in closes or quote.ts > closes[stock_id][1]
    }


@dataclass(frozen=True)
class PortfolioAnalysisRule:
    """
    The portfolio the holdings of every source make. Each position is valued (PositionValueRule) at its stock's last
    close held, or at today's quote where one of `quotes`, the held stocks' own, was traded after that close, so a
    session's settled close replaces its last quote; one with neither counts at its cost. A holding stays under its
    source: the same stock held at the broker and entered by hand is two holdings, each counted once, and one stock for
    the concentration.
    """

    position_value_rule: PositionValueRule
    concentration_positions: PositiveInt

    def apply(
        self,
        held: Mapping[HoldingSource, Sequence[Position]],
        closes: Mapping[str, tuple[float, datetime]],
        quotes: Mapping[str, Ohlcv],
        names: Mapping[str, str],
        standings: Mapping[str, RankingStanding],
        revenues: Mapping[str, RevenueTrend],
    ) -> PortfolioAnalysis:
        live = quoted_after(closes, quotes)
        prices = {**closes, **live}
        valued = [
            (source, self.position_value_rule.apply(position, *prices[position.stock_id]) if position.stock_id in prices else position)
            for source, positions in held.items()
            for position in positions
        ]
        total = math.fsum(position.market_value for _, position in valued)
        holdings = [
            AnalysedHolding(
                source=source,
                position=position,
                stock_name=names.get(position.stock_id),
                weight=min(1.0, position.market_value / total),
                standing=standings.get(position.stock_id),
                revenue=trend.months[-1] if (trend := revenues.get(position.stock_id)) and trend.months else None,
                accelerating_months=trend.accelerating_months if trend else None,
            )
            for source, position in sorted(valued, key=lambda pair: (-pair[1].market_value, pair[1].stock_id, pair[0]))
        ]
        return portfolio_analysis(sorted(held), holdings, sorted(live), total, self.concentration_positions)
