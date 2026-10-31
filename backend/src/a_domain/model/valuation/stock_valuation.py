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
from a_domain.rules.collect.freshness import DailyCloseFreshnessRule
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

    @property
    def eps(self) -> Eps | EpsUnavailable:
        return self.stock.eps

    @property
    def close_is_fresh(self) -> bool:
        return self.close is not None and DailyCloseFreshnessRule().is_fresh(self.close.ts.date(), self.last_closed_session)

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
            return "無有效收盤價"

        return f"{self.close.close:,.2f} 元（{self.close.ts:%Y-%m-%d} 收盤，交易所公告）"

    @property
    def pe_text(self) -> str:
        match self.current_pe:
            case PeRatio() as pe:
                return f"{pe.value:.2f} 倍"
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
                f"{quarter} 財報尚未納入（申報期限 {quarter.filing_deadline}；公司尚未申報或資料未能取得），"
                f"本次使用至 {eps.period_end} 的近四季 EPS"
                for quarter in eps.newer_quarters
            )

            if eps.value == 0:
                warnings.append("近四季 EPS 為 0，無法計算本益比，不使用本益比估值")
            elif eps.value < 0:
                warnings.append(f"近四季 EPS 為 {eps.value:.2f}（虧損），本益比不適用，不計算合理價")

        if self.close is None:
            warnings.append("無有效收盤價：最近交易日無成交或交易所資料缺漏")
        elif not self.close_is_fresh:
            session = self.close.ts.date()
            missed = DailyCloseFreshnessRule().missed_sessions(session, self.last_closed_session)
            warnings.append(f"股價過期：收盤日 {session}，其後已有 {missed} 個交易日收盤（最近收盤交易日 {self.last_closed_session}）")

        return tuple(warnings)
