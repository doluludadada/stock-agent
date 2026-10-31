from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date

from a_domain.model.fundamentals.eps import Eps
from a_domain.model.fundamentals.eps_unavailable import EpsUnavailable
from a_domain.model.market.ohlcv import Ohlcv
from a_domain.model.market.stock import Stock
from a_domain.model.valuation.pe_not_applicable import PeNotApplicable
from a_domain.model.valuation.pe_ratio import PeRatio
from a_domain.rules.collect.freshness import DailyCloseFreshnessRule, MissedSessionsRule
from a_domain.types.enums import PeNotApplicableReason

type PeOutcome = PeRatio | PeNotApplicable


@dataclass(frozen=True)
class StockValuation:
    """
    One stock's valuation inputs before any user assumption: its EPS and the exchange's latest official close.

    EPS is read through the stock, whose only writer is FundamentalsFeed. P/E, freshness and warnings are derived.
    """

    stock: Stock
    close: Ohlcv | None
    last_closed_session: date
    max_missed_sessions: int
    """How many weekday sessions may close after the close's session before the close is stale."""

    @property
    def eps(self) -> Eps | EpsUnavailable:
        return self.stock.eps

    @property
    def close_is_fresh(self) -> bool:
        return self.close is not None and DailyCloseFreshnessRule(self.max_missed_sessions).apply(
            self.close.ts.date(), self.last_closed_session
        )

    @property
    def needs_target_pe(self) -> bool:
        """Its P/E is computable, so valuing it needs the user's target P/E. Otherwise it has no fair price to compute."""
        return isinstance(self.current_pe, PeRatio)

    @property
    def current_pe(self) -> PeOutcome:
        eps = self.eps

        if isinstance(eps, EpsUnavailable):
            return PeNotApplicable(PeNotApplicableReason.EPS_UNAVAILABLE)

        if eps.value == 0:
            return PeNotApplicable(PeNotApplicableReason.EPS_ZERO)

        if eps.value < 0:
            return PeNotApplicable(PeNotApplicableReason.EPS_NEGATIVE)

        if self.close is None or not math.isfinite(self.close.close) or self.close.close <= 0:
            return PeNotApplicable(PeNotApplicableReason.INVALID_PRICE)

        return PeRatio(price=self.close.close, eps=eps.value)

    @property
    def price_text(self) -> str:
        if self.close is None:
            return "no valid close"

        return f"{self.close.close:,.2f} TWD ({self.close.ts:%Y-%m-%d} close, published by the exchange)"

    @property
    def pe_text(self) -> str:
        match self.current_pe:
            case PeRatio() as pe:
                return f"{pe.value:.2f}x"
            case PeNotApplicable(reason=reason):
                return reason.label

    @property
    def warnings(self) -> tuple[str, ...]:
        warnings: list[str] = []
        eps = self.eps

        if isinstance(eps, EpsUnavailable):
            warnings.append(eps.describe())
        else:
            warnings.extend(
                f"{quarter} filings are not included (filing deadline {quarter.filing_deadline}; the company has not "
                f"filed yet or the data could not be fetched), so this run uses the TTM EPS through {eps.period_end}"
                for quarter in eps.newer_quarters
            )

            if eps.value == 0:
                warnings.append("The TTM EPS is 0, so the P/E cannot be computed and no P/E valuation is made")
            elif eps.value < 0:
                warnings.append(f"The TTM EPS is {eps.value:.2f} (a loss), so the P/E does not apply and no fair price is computed")

        if self.close is None:
            warnings.append("No valid close: no trade in the latest session, or the exchange data is missing")
        elif not self.close_is_fresh:
            session = self.close.ts.date()
            missed = MissedSessionsRule().apply(session, self.last_closed_session)
            warnings.append(
                f"Stale price: closed on {session}, and {missed} sessions have closed since "
                f"(last closed session {self.last_closed_session})"
            )

        return tuple(warnings)
